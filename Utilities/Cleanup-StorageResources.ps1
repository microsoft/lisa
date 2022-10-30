param(
    [String] $TenantId,
    [String] $ClientId,
    [String] $ClientSecret,
    [String] $SubscriptionId,
    [String] $SkippedStorageAccountNames,
    [String] $Resource = "https://management.core.windows.net/",
    [String] $APIVersion = "2020-06-01",
    [String] $SCAPIVersion = "2021-08-01"
)

Function GetTokenStringToSign
{
    [CmdletBinding()]
    param
    (
        [Parameter(Mandatory = $false,ValueFromPipelineByPropertyName = $true)]
        [ValidateSet('GET','PUT','DELETE')]
        [string]$Verb="GET",
        [Parameter(Mandatory=$true,ValueFromPipelineByPropertyName = $true)]
        [System.Uri]$Resource,
        [Parameter(Mandatory = $false,ValueFromPipelineByPropertyName = $true)]
        [long]$ContentLength,
        [Parameter(Mandatory = $false,ValueFromPipelineByPropertyName = $true)]
        [String]$ContentLanguage,
        [Parameter(Mandatory = $false,ValueFromPipelineByPropertyName = $true)]
        [String]$ContentEncoding,
        [Parameter(Mandatory = $false,ValueFromPipelineByPropertyName = $true)]
        [String]$ContentType,
        [Parameter(Mandatory = $false,ValueFromPipelineByPropertyName = $true)]
        [String]$ContentMD5,
        [Parameter(Mandatory = $false,ValueFromPipelineByPropertyName = $true)]
        [long]$RangeStart,
        [Parameter(Mandatory = $false,ValueFromPipelineByPropertyName = $true)]
        [long]$RangeEnd,[Parameter(Mandatory = $true,ValueFromPipelineByPropertyName = $true)]
        [System.Collections.IDictionary]$Headers
    )

    $ResourceBase=($Resource.Host.Split('.') | Select-Object -First 1).TrimEnd("`0")
    $ResourcePath=$Resource.LocalPath.TrimStart('/').TrimEnd("`0")
    $LengthString=[String]::Empty
    $Range=[String]::Empty
    if($ContentLength -gt 0){$LengthString="$ContentLength"}
    if($RangeEnd -gt 0){$Range="bytes=$($RangeStart)-$($RangeEnd-1)"}

    $SigningPieces = @($Verb, $ContentEncoding,$ContentLanguage, $LengthString,$ContentMD5, $ContentType, [String]::Empty, [String]::Empty, [String]::Empty, [String]::Empty, [String]::Empty, $Range)
    foreach ($item in $Headers.Keys)
    {
        $SigningPieces+="$($item):$($Headers[$item])"
    }
    $SigningPieces+="/$ResourceBase/$ResourcePath"

    if ([String]::IsNullOrEmpty($Resource.Query) -eq $false)
    {
        $QueryResources=@{}
        $QueryParams=$Resource.Query.Substring(1).Split('&')
        foreach ($QueryParam in $QueryParams)
        {
            $ItemPieces=$QueryParam.Split('=')
            $ItemKey = ($ItemPieces|Select-Object -First 1).TrimEnd("`0")
            $ItemValue = ($ItemPieces|Select-Object -Last 1).TrimEnd("`0")
            if($QueryResources.ContainsKey($ItemKey))
            { 
                $QueryResources[$ItemKey] = "$($QueryResources[$ItemKey]),$ItemValue"    
            }
            else
            {
                $QueryResources.Add($ItemKey, $ItemValue)
            }
        }
        $Sorted=$QueryResources.Keys|Sort-Object
        foreach ($QueryKey in $Sorted)
        {
            $SigningPieces += "$($QueryKey):$($QueryResources[$QueryKey])"
        }
    }

    $StringToSign = [String]::Join("`n",$SigningPieces)
    Write-Output $StringToSign 
}
Function EncodeStorageRequest
{
    [CmdletBinding()]
    param
    (
        [Parameter(Mandatory = $true,ValueFromPipeline=$true,ValueFromPipelineByPropertyName=$true)]
        [String[]]$StringToSign,
        [Parameter(Mandatory=$true,ValueFromPipelineByPropertyName=$true)]
        [String]$SigningKey
    )
    PROCESS
    {         
        foreach ($item in $StringToSign)
        {
            $KeyBytes = [System.Convert]::FromBase64String($SigningKey)
            $HMAC = New-Object System.Security.Cryptography.HMACSHA256
            $HMAC.Key = $KeyBytes
            $UnsignedBytes = [System.Text.Encoding]::UTF8.GetBytes($item)
            $KeyHash = $HMAC.ComputeHash($UnsignedBytes)
            $SignedString=[System.Convert]::ToBase64String($KeyHash)
            Write-Output $SignedString 
        }     
    }
}

# Get A Token
$RequestAccessTokenUri = "https://login.microsoftonline.com/$TenantId/oauth2/token"
$body = "grant_type=client_credentials&client_id=$ClientId&client_secret=$ClientSecret&resource=$Resource"
$Token = Invoke-RestMethod -Method Post -Uri $RequestAccessTokenUri -Body $body -ContentType 'application/x-www-form-urlencoded'
if ($?) {
    Write-Host "******************************************************************************************************************************"
    Write-Host "Get a token successfully for subscription $SubscriptionId." -ForegroundColor Green
    Write-Host "Start to cleanup Storage resource for subscription $SubscriptionId."
} else {
    Write-Host "Fail to get a token." -ForegroundColor Red
    return
}

$SecureStringPwd = $ClientSecret | ConvertTo-SecureString -AsPlainText -Force
$pscredential = New-Object -TypeName System.Management.Automation.PSCredential -ArgumentList $ClientId, $SecureStringPwd
Connect-AzAccount -ServicePrincipal -Credential $pscredential -Tenant $TenantId

# get all storage accounts under the sub
$SCApiUri = "https://management.azure.com/subscriptions/$SubscriptionId/providers/Microsoft.Storage/storageAccounts?api-version=2015-06-15&%24expand=createdTime,changedTime"
$Headers = @{}
$Headers.Add("Authorization","$($Token.token_type) "+ " " + "$($Token.access_token)")
$StorageAccount = Invoke-RestMethod -Method Get -Uri $SCApiUri -Headers $Headers
$index = 0
foreach ($value in $StorageAccount.value) {
    $index = $index + 1
    $rgName = $value.id.Split('/')[4]
    $scname = $value.name
    Write-Host "Storage account name - $index $scname."
    if ($SkippedStorageAccountNames -and $SkippedStorageAccountNames.Contains($scname)) {
        Write-LogInfo "Skipping $scname. Storage account marked for skip."
        continue
    }
    # get all containers under the storage account
    $containerApiUri = "https://management.azure.com/subscriptions/$SubscriptionId/resourceGroups/$rgName/providers/Microsoft.Storage/storageAccounts/$scname/blobServices/default/containers?api-version=2021-06-01"
    $containers = Invoke-RestMethod -Method Get -Uri $containerApiUri -Headers $Headers

    foreach($container in $containers.value) {
        $container_name = $container.name
        # just delete bootdiagnostics container
        if($container_name.contains("bootdiagnostics-")) {
            Write-Host "container name - $container_name."
            # by default, delete it
            $delete = $true
            $vmid = $container_name.Split("-")[2]+"-"+$container_name.Split("-")[3]+"-"+$container_name.Split("-")[4]+"-"+$container_name.Split("-")[5]+"-"+$container_name.Split("-")[6]
            $vmapi="https://management.azure.com/subscriptions/$SubscriptionId/providers/Microsoft.Compute/virtualMachines?api-version=$APIVersion"
            $vmlist = Invoke-RestMethod -Method Get -Uri $vmapi -Headers $Headers
            foreach($vm in $vmlist.value) {
                if($vm.properties.vmId -eq $vmid) {
                    # if the VM still exists, not delete this container
                    $delete = $false
                    $vmname = $vm.name
                    break
                }
            }
            write-host $container.name $container.properties.lastModifiedTime
            if (!$delete) {
                write-host "Storage account $scname - container $container_name can't be deleted, the VM $vmname still exist."
            } else {
                $return = Invoke-RestMethod -Method Post -Uri "https://management.azure.com/subscriptions/$SubscriptionId/resourceGroups/$rgName/providers/Microsoft.Storage/storageAccounts/$scname/listKeys?api-version=2021-09-01" -Headers $Headers
                $key = $return.keys[0][0].value
                write-host "Storage account $scname - container $container_name can be deleted"

                $Context = New-AzStorageContext -StorageAccountName $scname -StorageAccountKey $key
                write-host "Remove-AzStorageContainer -Name $container_name -Context $Context -Force"
                Remove-AzStorageContainer -Name $container_name -Context $Context -Force
                if ($?) {
                    Write-Host "Delete container $container_name successfully." -ForegroundColor Green
                } else {
                    Write-Host "Fail to delete container $container_name. Please delete it manually." -ForegroundColor Red
                }
            }
        } else {
            $keyapi = "https://management.azure.com/subscriptions/$SubscriptionId/resourceGroups/$rgName/providers/Microsoft.Storage/storageAccounts/$scname/listKeys?api-version=2021-06-01"
            $keys = Invoke-RestMethod -Method Post -Uri $keyapi -Headers $Headers
            $key = $keys.keys[0].value
            $BlobHeaders= @{
                "x-ms-date"=[DateTime]::UtcNow.ToString('R');
                "x-ms-version"='2016-05-31'; 
            }
            $listblobapi = "https://$scname.blob.core.windows.net/${container_name}?restype=container&comp=list&maxresults=5000"
            $UnsignedSignature = GetTokenStringToSign -Verb GET -Resource $listblobapi -Headers $BlobHeaders
            $StorageSignature = EncodeStorageRequest -StringToSign $UnsignedSignature -SigningKey $key 
            #Now we should have a 'token' for our actual request. 
            $BlobHeaders.Add('Authorization',"SharedKey $($scname):$($StorageSignature)") 
            $Result = Invoke-RestMethod -Uri $listblobapi -Headers $BlobHeaders

            $UTF8ByteOrderMark = [System.Text.Encoding]::Default.GetString([System.Text.Encoding]::UTF8.GetPreamble())
            if($Result.StartsWith($UTF8ByteOrderMark,[System.StringComparison]::Ordinal)) {
                $Result=$Result.Remove(0,$UTF8ByteOrderMark.Length)
            }
            [Xml]$EnumerationResult = $Result

            foreach($blob in $EnumerationResult.EnumerationResults.Blobs.Blob) {
                $currentTimeStamp = get-date
                $blob_name = $blob.name

                $blobDate = [DateTime]($blob.Properties.'Last-Modified')
                if((($currentTimeStamp - $blobDate).Days -ge 7) -and ($blob_name.StartsWith("LISAv2") -or $blob_name.StartsWith("EOSG-AUTOBUILT") -or $blob_name.StartsWith("lsg-")) -and $blob_name.EndsWith(".vhd")) {
                    write-host "delete $blob_name"
                    $context = New-AzStorageContext -StorageAccountName $scname -StorageAccountKey $key
                    write-host "Remove-AzStorageBlob -Container $container_name -Blob $blob_name -Context $context"
					Remove-AzStorageBlob -Container $container_name -Blob $blob_name -Context $context
                }
            }
        }
    }
}
Write-Host "End to cleanup Storage resource for subscription $SubscriptionId."
Write-Host "******************************************************************************************************************************"
