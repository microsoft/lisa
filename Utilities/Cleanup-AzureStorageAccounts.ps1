
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Description
    This is a script that performs Azure Storage Cleanup.

.EXAMPLE
    1. Run script in default mode.
        In default mode, this script will remove 7+ days old files from -
        1. bootdiagnostics* containers. (File extension *.*)
        2. LISAv2 generated VHDs. (File extension *.vhd. Patterns: "LISAv2 / -osdisk.vhd /AUTOBUILT ")
        3. Cleanup regions : ALL
        4. Cleanup storage accounts : ALL
        5. Cleanup containers : vhds, bootdiagnostics*

    Command: .\Utilities\Cleanup-AzureStorageAccounts.ps1 -SecretFilePath .\XML\AzureSecrets_Test_ONLY.xml

    2. Limit cleanup to specific region and / or specific storage accounts.

    Command: .\Utilities\Cleanup-AzureStorageAccounts.ps1 -SecretFilePath .\XML\AzureSecrets_Test_ONLY.xml `
        -AzureRegions "westus2,westus" -StorageAccountNames "abc1,abc2"

    3. Remove a specific VHD from all storage accounts / regions.

    Command: .\Utilities\Cleanup-AzureStorageAccounts.ps1 -SecretFilePath .\XML\AzureSecrets_Test_ONLY.xml `
        -VHDNames "EOSG-AUTOBUILT-ABC.vhd"

    4. Remove VHDs based on string patterns.

    Command: .\Utilities\Cleanup-AzureStorageAccounts.ps1 -SecretFilePath .\XML\AzureSecrets_Test_ONLY.xml `
        -Patterns "AUTOBUILT,LISAv2"

    5. [DryRun] Cleanup all** data from all storage accounts, older than 1 year.

    Command: .\Utilities\Cleanup-AzureStorageAccounts.ps1 -SecretFilePath .\XML\AzureSecrets_Test_ONLY.xml `
        -Patterns "" -CleanupAgeInDays 365 -DryRun

Important Notes:
================
    1.  Empty <-Patterns ""> value selects all the files in given containers.
    2.  If you are not sure about what is being cleaned up, then use -DryRun mode.
        Then, examine the .csv file created, which shows list of files and cleanup status.
        If you're satisfied with dryrun cleanup list, remove -DryRun and run the cleanup.
#>

param(
    [String] $SecretFilePath,

    # Comma separated storage account names. If empty, All storage accounts in current subscriptions will be selected.
    [string] $StorageAccountNames,

    # Comma separated skipped Storage account names.
    [string] $SkippedStorageAccountNames,

    # Comma separated Azure regions. If empty, All regions in current subscriptions will be selected.
    [string] $AzureRegions,

    # Comma separated values of exact VHD names to clean.
    [String] $VHDNames,

    # Command separated VHD name patterns to clean.
    [String] $Patterns = "LISAv2,-osdisk.vhd,AUTOBUILT",

    # Cleanup Age (in Days)
    [int] $CleanupAgeInDays = 7,

    # Switch to enable logs for skipped files. (Makes execution slower).
    [switch] $ShowSkippedFiles,

    # Switch to enable dry run mode.
    [switch] $DryRun
)


try {
    #region Authenticate the powershell session.
    if ($SecretFilePath) {
        .\Utilities\AddAzureRmAccountFromSecretsFile.ps1 -customSecretsFilePath $SecretFilePath
        $SelectedSubscription = Get-AzSubscription
        $SubID = $SelectedSubscription.Id
        $SubName = $SelectedSubscription.Name
    } else {
        Write-LogInfo "Secret File not provided. Checking subscriptions..."
        $Subscriptions = Get-AzSubscription
        if ($Subscriptions) {
            $SubscriptionCount = $Subscriptions.Count
            if ($SubscriptionCount -eq 1) {
                $SubID = $Subscriptions.Id
                $SubName = $Subscriptions.Name
            } else {
                $ChoiceString = ""
                $ChoiceCounter =  1
                $Subscriptions | ForEach-Object {
                    Write-LogInfo "$ChoiceCounter. $($_.Name) ($($_.Id))"
                    $ChoiceString += "$ChoiceCounter/"
                    $ChoiceCounter += 1;
                }
                $ChoiceString = $ChoiceString.TrimEnd('/')
                $UserChoice = 0
                while ($UserChoice -gt ( $ChoiceCounter -1 ) -or $UserChoice -le 0) {
                    Write-LogWarn "Please make sure that you choose correct subscription for storage cleanup."
                    $UserChoice = [int] (Read-Host "Enter your choice. [$ChoiceString]")
                }
                $SubID = $Subscriptions[$UserChoice -1].Id
                $SubName = $Subscriptions[$UserChoice -1].Name
            }
            Write-LogInfo "Selected - '$SubName ($SubID)'."

            # Get the final confirmation from user
            $RandomNumber = Get-Random -Minimum 1111 -Maximum 9999
            while ($UserChoice -ne $RandomNumber) {
                $RandomNumber = Get-Random -Minimum 1111 -Maximum 9999
                $UserChoice = [int] (Read-Host "Enter this number to confirm. [$RandomNumber]")
            }
            $null = Select-AzSubscription -Subscription $SubID
        } else {
            Write-LogErr "Powershell Session is not authenticated / User doesn't have access to any subscription. Exiting."
            exit 1
        }
    }
    #endregion
    Function Test-Pattern ($FileName, $Patterns) {
        $retValue = $false
        if ( $Patterns ) {
            $Patterns = $Patterns.Split(",")
            foreach ($item in $Patterns) {
                if ($FileName -imatch $item) {
                    $retValue = $true
                    break;
                }
            }
        }
        return $retValue
    }

    Function Get-FileAge ($File) {
        $FileCreationTime = $File.ICloudBlob.Properties.Created.UtcDateTime
        $CurrentTime = (Get-Date).ToUniversalTime()
        $FileAge = ($CurrentTime - $FileCreationTime).Days
        return $FileAge
    }

    Function New-FileObject ($File) {
        $FileObject = New-Object -TypeName psobject
        $FileObject | Add-Member -MemberType NoteProperty -Name SubscriptionId -Value $SubID
        $FileObject | Add-Member -MemberType NoteProperty -Name SubscriptionName -Value $SubName
        $FileObject | Add-Member -MemberType NoteProperty -Name FileName -Value $File.Name
        $size = [math]::Round($File.Length / 1GB, 3)
        $FileObject | Add-Member -MemberType NoteProperty -Name Size -Value $size
        $FileObject | Add-Member -MemberType NoteProperty -Name Age -Value $null
        $FileObject | Add-Member -MemberType NoteProperty -Name LockStatus -Value $File.ICloudBlob.Properties.LeaseStatus
        $FileObject | Add-Member -MemberType NoteProperty -Name StorageAccount -Value $File.ICloudBlob.ServiceClient.StorageUri.PrimaryUri.Host.Split(".")[0]
        $FileObject | Add-Member -MemberType NoteProperty -Name ResourceGroup -Value $null
        $FileObject | Add-Member -MemberType NoteProperty -Name Region -Value $null
        $FileObject | Add-Member -MemberType NoteProperty -Name Created -Value $File.ICloudBlob.Properties.Created.UtcDateTime
        $FileObject | Add-Member -MemberType NoteProperty -Name Modified -Value $File.ICloudBlob.Properties.LastModified.UtcDateTime
        $FileObject | Add-Member -MemberType NoteProperty -Name VMName -Value $File.ICloudBlob.Metadata["MicrosoftAzureCompute_VMName"]
        $FileObject | Add-Member -MemberType NoteProperty -Name VMResourceGroup -Value $File.ICloudBlob.Metadata["MicrosoftAzureCompute_ResourceGroupName"]
        $FileObject | Add-Member -MemberType NoteProperty -Name URL -Value $File.ICloudBlob.Uri.AbsoluteUri
        $FileObject | Add-Member -MemberType NoteProperty -Name CleanupStatus -Value "Skipped"
        return $FileObject
    }


    # Start main body ..
    Write-LogInfo "Getting list of all storage accounts ..."
    $storageAccounts = Get-AzStorageAccount
    $AllFiles = @()
    $CleanedFiles = 0
    $SkippedFiles = 0
    $Counter = 0
    $AllFileObject = @()
    if ($AzureRegions) {
        [array] $AzureRegions = $AzureRegions.Split(",")
    } else {
        [array] $AzureRegions = (Get-AzLocation | Where-Object { $_.Providers -imatch "Microsoft.Compute" `
                    -and $_.Providers -imatch "Microsoft.Storage" -and $_.Providers -imatch "Microsoft.Network" }).location | Sort-Object
    }
    if ($StorageAccountNames) {
        [array] $StorageAccountNames = $StorageAccountNames.Split(",")
    } else {
        [array] $StorageAccountNames = $storageAccounts.StorageAccountName
    }
    if ($SkippedStorageAccountNames) {
        [array] $SkippedStorageAccountNames = $SkippedStorageAccountNames.Split(",")
    }
    $StorageAccountCounter = 0
    foreach ($storageAccount in $storageAccounts) {
        $StorageAccountCounter += 1
        $CurrentRegion = $storageAccount.Location
        if (-not $AzureRegions.Contains($CurrentRegion)) {
            if ($ShowSkippedFiles) { Write-LogInfo "Skipping $($storageAccount.Location). Region not given for cleanup." }
            continue;
        }
        if (-not $StorageAccountNames.Contains($storageAccount.StorageAccountName)) {
            if ($ShowSkippedFiles) { Write-LogInfo "Skipping $($storageAccount.StorageAccountName). Storage account not given for cleanup." }
            continue;
        }
        if ( $SkippedStorageAccountNames.Contains($storageAccount.StorageAccountName)) {
            if ($ShowSkippedFiles) { Write-LogInfo "Skipping $($storageAccount.StorageAccountName). Storage account marked for skip." }
            continue;
        }
        Write-LogInfo "[Storage Account : $StorageAccountCounter/$($storageAccounts.Count)] Current Storage Account: $($storageAccount.StorageAccountName). Region: $CurrentRegion"
        Write-LogInfo "Get-AzStorageAccountKey -ResourceGroupName $($storageAccount.ResourceGroupName) -Name $($storageAccount.StorageAccountName)..."
        $storageKey = (Get-AzStorageAccountKey -ResourceGroupName $storageAccount.ResourceGroupName -Name $storageAccount.StorageAccountName)[0].Value
        $context = New-AzStorageContext -StorageAccountName $storageAccount.StorageAccountName -StorageAccountKey $storageKey
        Write-LogInfo "Get-AzStorageContainer..."
        $containers = Get-AzStorageContainer -Context $context -ConcurrentTaskCount 64
        $containerCounter = 0
        foreach ($container in $containers) {
            $blobCounter = 0
            $containerCounter += 1

            $isBootDiagContainer = $container.Name -imatch "bootdiagnostics"

            if ($isBootDiagContainer -and (-not $VHDNames) ) {
                $blobs = Get-AzStorageBlob -Container $container.Name -Context $context
            } elseif ($container.Name -eq "vhds") {
                $blobs = Get-AzStorageBlob -Container $container.Name -Context $context | Where { $_.Name.EndsWith(".vhd") }
            } else {
                if ($ShowSkippedFiles) { Write-LogInfo "[Container $containerCounter/$($containers.Count). Skipped : $($container.Name)" }
                continue;
            }
            Write-LogInfo "[Container : $containerCounter/$($containers.Count)]. Get-AzStorageBlob -Container $($container.Name) ..."

            foreach ($blob in $blobs) {
                $blobCounter += 1
                $FileAge = Get-FileAge -File $blob
                $CurrentFileObject = New-FileObject -File $blob
                $CurrentFileObject.ResourceGroup = $storageAccount.ResourceGroupName
                $CurrentFileObject.Age = $FileAge
                $CurrentFileObject.Region = $CurrentRegion
                $AllFileObject += $CurrentFileObject
                $FileURI = $($blob.ICloudBlob.Uri.AbsoluteUri)
                if ($VHDNames) {
                    $VHDNames = $VHDNames.Split(",")
                    if ( -not ( $VHDNames.Contains($blob.Name)) ) {
                        if ($ShowSkippedFiles) { Write-LogInfo "[File : $blobCounter/$($blobs.Count)]. $FileURI : Skipped (VHD Name not matched: $VHDNames)" }
                        $SkippedFiles += $blob.Length
                        continue;
                    }
                }
                if ($CleanupAgeInDays -ne $null) {
                    if ( $FileAge -le $CleanupAgeInDays) {
                        if ($ShowSkippedFiles) { Write-LogInfo "[File : $blobCounter/$($blobs.Count)]. $FileURI : Skipped (File Age  ($FileAge) <= $CleanupAgeInDays)" }
                        $SkippedFiles += $blob.Length
                        continue;
                    } else {
                        $DeleteAgeString = "$FileAge days old"
                    }
                } else {
                    $DeleteAgeString = $null
                }
                if ($Patterns -and !$isBootDiagContainer) {
                    if ( -not (Test-Pattern -FileName $blob.Name -Pattern $Patterns) ) {
                        if ($ShowSkippedFiles) { Write-LogInfo "[File : $blobCounter/$($blobs.Count)]. $FileURI : Skipped (Pattern '$Patterns' not found)" }
                        $SkippedFiles += $blob.Length
                        continue;
                    }
                }
                if (-not ($blob.ICloudBlob.Properties.LeaseStatus -eq 'Unlocked')) {
                    if ($ShowSkippedFiles) { Write-LogInfo "[$File : blobCounter/$($blobs.Count)]. $FileURI : Skipped (Locked)" }
                    $SkippedFiles += $blob.Length
                    continue;
                }
                $Counter += 1
                $AllFiles += $blob
                $CleanedFiles += $blob.Length
                if (-not $DryRun) {
                    Write-LogInfo "[File : $blobCounter/$($blobs.Count)]. [Deleted Files=$Counter]. Deleting $DeleteAgeString unlocked File with Uri: $($blob.ICloudBlob.Uri.AbsoluteUri)"
                    $null = $blob | Remove-AzStorageBlob -Force
                    if ($?) {
                        $AllFileObject[-1].CleanupStatus = "Deleted"
                    } else {
                        $AllFileObject[-1].CleanupStatus = "Failed"
                    }
                } else {
                    Write-LogInfo "[DryRun] [File : $blobCounter/$($blobs.Count)]. [Deleted Files=$Counter]. Deleting $DeleteAgeString unlocked File with Uri: $($blob.ICloudBlob.Uri.AbsoluteUri)"
                    $AllFileObject[-1].CleanupStatus = "[DryRun] Deleted"
                }
            }
            if (-not $DryRun) {
                $blobs = Get-AzStorageBlob -Container $container.Name -Context $context
                if ($isBootDiagContainer -and $blobs.Count -eq 0) {
                    Write-LogInfo "Removing empty container $($container.Name)"
                    Remove-AzStorageContainer -Name  $container.Name -Force -Context $context
                }
            }
        }
    }

    $LogFileName = "Azure-Storage-Cleanup-$SubName-$(Get-Date -format 'yyyyMMdd-HHMMss').csv"
    Write-LogInfo "Creating CSV file '$LogFileName'..."
    $AllFileObject | Export-Csv -Path "$LogFileName" -Force
    Write-LogInfo "Done."
} catch {
    Write-LogErr "Exception in Cleanup-AzureStorageAccount.ps1."
    $line = $_.InvocationInfo.ScriptLineNumber
    $script_name = ($_.InvocationInfo.ScriptName).Replace($PWD,".")
    $ErrorMessage =  $_.Exception.Message
    Write-LogInfo "EXCEPTION : $ErrorMessage"
    Write-LogInfo "Source : Line $line in script $script_name."
} finally {
    $CleanedFilesSizeInGb = [math]::Round( $CleanedFiles / 1GB, 3 )
    $SkippedFilesSizeInGb = [math]::Round( $SkippedFiles / 1GB, 3 )
    $TotalFilesSizeInGb = $CleanedFilesSizeInGb + $SkippedFilesSizeInGb
    Write-LogInfo "Cleaned Files : $($CleanedFilesSizeInGb) GB"
    Write-LogInfo "Skipped Files : $($SkippedFilesSizeInGb) GB"
    Write-LogInfo "Total Files   : $($TotalFilesSizeInGb) GB"
}