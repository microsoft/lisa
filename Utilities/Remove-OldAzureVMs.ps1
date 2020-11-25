
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Description
        This is a script that performs a cleanup on LISAv2 Azure VMs.
#>

param(
    [String] $customSecretsFilePath,
    [int] $CleanupAgeInDays,
    [int] $LockedResourceAgeInDays,
    [switch] $RemoveAutoCleanupVMs,
    [switch] $DryRun,
    [switch] $RemoveDisks
)

if ( $customSecretsFilePath ) {
    $secretsFile = $customSecretsFilePath
    Write-Host "Using provided secrets file: $($secretsFile | Split-Path -Leaf)"
}
if ($env:Azure_Secrets_File) {
    $secretsFile = $env:Azure_Secrets_File
    Write-Host "Using predefined secrets file: $($secretsFile | Split-Path -Leaf) in Jenkins Global Environments."
}
if ( $null -eq $secretsFile ) {
    Write-Host "ERROR: Azure Secrets file not found in Jenkins / user not provided -customSecretsFilePath" -ForegroundColor Red -BackgroundColor Black
    exit 1
}
if ( Test-Path $secretsFile) {
    Write-Host "$($secretsFile | Split-Path -Leaf) found."
    .\Utilities\AddAzureRmAccountFromSecretsFile.ps1 -customSecretsFilePath $secretsFile
}
else {
    Write-Host "$($secretsFile | Split-Path -Leaf) file is not added in Jenkins Global Environments OR it is not bound to 'Azure_Secrets_File' variable." -ForegroundColor Red -BackgroundColor Black
    Write-Host "Aborting." -ForegroundColor Red -BackgroundColor Black
    exit 1
}

$FinalHtmlFile = ".\VMsWithLock.html"
$EmailSubjectTextFile = ".\ShowVMsWithLockEmailSubject.txt"
if ([System.IO.File]::Exists($FinalHtmlFile)) {
    Remove-Item $FinalHtmlFile
}
if ([System.IO.File]::Exists($EmailSubjectTextFile)) {
    Remove-Item $EmailSubjectTextFile
}
$pstzone = [System.TimeZoneInfo]::FindSystemTimeZoneById("Pacific Standard Time")
$psttime = [System.TimeZoneInfo]::ConvertTimeFromUtc((Get-Date).ToUniversalTime(), $pstzone)
$FinalEmailSummary = ""
#region HTML file header
$htmlFileStart = '
<style type="text/css">
.tg  {border-collapse:collapse;border-spacing:0;border-color:#999;}
.tg td{font-family:Arial, sans-serif;font-size:14px;padding:10px 5px;border-style:solid;border-width:1px;overflow:hidden;word-break:normal;border-color:#999;color:#444;background-color:#F7FDFA;}
.tg th{font-family:Arial, sans-serif;font-size:14px;font-weight:normal;padding:10px 5px;border-style:solid;border-width:1px;overflow:hidden;word-break:normal;border-color:#999;color:#fff;background-color:#26ADE4;}
.tg .tg-baqh{text-align:left;vertical-align:top}
.tg .tg-lqy6{text-align:right;vertical-align:top}
.tg .tg-lqy6bold{font-weight:bold;text-align:right;vertical-align:top}
.tg .tg-yw4l{vertical-align:top}
.tg .tg-amwm{font-weight:bold;text-align:right;vertical-align:top}
.tg .tg-amwmleft{text-align:left;font-weight:bold;vertical-align:top}
.tg .tg-amwmred{color:#fe0000;font-weight:bold;text-align:right;vertical-align:top}
.tg .tg-amwmgreen{color:#036400;font-weight:bold;text-align:right;vertical-align:top}
.tg .tg-9hbo{font-weight:bold;vertical-align:top}
.tg .tg-l2oz{font-weight:bold;text-align:right;vertical-align:top}
.tg .tg-l2ozred{color:#fe0000;font-weight:bold;text-align:right;vertical-align:top}
.tg .tg-l2ozgreen{color:#036400;font-weight:bold;text-align:right;vertical-align:top}
</style>
'
#endregion

#region HTML File row
$htmlFileRow = '
  <tr>
    <td class="tg-amwmleft">Current_Serial</td>
    <td class="tg-amwmleft">ResourceGroupName</td>
    <td class="tg-amwmleft">LockName</td>
    <td class="tg-amwmleft">LockLevel</td>
    <td class="tg-amwmleft">Age</td>
  </tr>
'
#endregion

$Report = '
<table class="tg">
  <tr>
    <th class="tg-amwmleft">SR. #</th>
    <th class="tg-amwmleft">ResourceGroupName</th>
    <th class="tg-amwmleft">LockName</th>
    <th class="tg-amwmleft">LockLevel</th>
    <th class="tg-amwmleft">Age</th>
  </tr>
  '
$AllResourceGroups = Get-AzResourceGroup
$AllLISAv2RGs = $AllResourceGroups | Where-Object { (($_.ResourceGroupName -imatch "ICA-RG-") -or `
    ($_.ResourceGroupName -imatch "LISAv2-") -and ($_.ResourceGroupName -inotmatch "LISAv2-storage-"))}
$AutoClenaupVMs = ($AllResourceGroups | Where-Object { $_.Tags.AutoCleanup })
$currentTimeStamp = Get-Date
$counter = 0
$lockcounter = 0
$cleanupRGs = @()
$allLocks = Get-AzResourceLock
foreach ($rg in $AllLISAv2RGs) {
    $counter += 1
    if ( $rg.Tags.AutoCleanup ) {
        if ( -not $RemoveAutoCleanupVMs) {
            Write-Host "$counter. $($rg.ResourceGroupName) - AutoCleanup tag detected. Use -RemoveAutoCleanupVMs to enalbe cleanup."
        } else {
            $counter -= 1
        }
    } else {
        $rgTimeStamp = [datetime]::MinValue
        $creationTimeTag = $rg.Tags.CreationTime
        if ($creationTimeTag) {
            [datetime]::TryParse($creationTimeTag, [ref]$rgTimeStamp) | Out-Null
        }
        if ($rgTimeStamp -eq [datetime]::MinValue) {
            $rgNameTimeAppendix = $($rg.ResourceGroupName).Split("-") | Select-Object -Last 1
            if ($rgNameTimeAppendix) {
                if ($rg.ResourceGroupName -imatch "LISAv2-") {
                    if (![datetime]::TryParseExact($rgNameTimeAppendix, "yyyyMMddHHmmss", $null, [System.Globalization.DateTimeStyles]::None, [ref]$rgTimeStamp)) {
                        [datetime]::TryParseExact($rgNameTimeAppendix, "MMddHHmmss", $null, [System.Globalization.DateTimeStyles]::None, [ref]$rgTimeStamp) | Out-Null
                    }
                }
                if (($rgTimeStamp -eq [datetime]::MinValue) -and ($rg.ResourceGroupName -imatch "ICA-RG-")) {
                    try {
                        $rgTimeStamp = [datetime]([long]($("${rgNameTimeAppendix}000000")))
                    }
                    catch {
                        Write-Host "$counter. $($rg.ResourceGroupName) - Could not parse/convert resource group Creation Time Stamp from Resource Group Name [${rgNameTimeAppendix}000000]"
                    }
                }
            }
        }
        if ($rgTimeStamp -ne [datetime]::MinValue) {
            $elaplsedDays = ($($currentTimeStamp - $rgTimeStamp)).Days
            if ($elaplsedDays -gt $CleanupAgeInDays) {
                Write-Host "$counter. $($rg.ResourceGroupName) - $elaplsedDays days old. Will be removed."
                $cleanupRGs += $rg.ResourceGroupName
                $lock = $allLocks | Where-Object { $_.ResourceGroupName -eq $rg.ResourceGroupName }
                if ($lock -and ($elaplsedDays -gt $LockedResourceAgeInDays)) {
                    $lockcounter = $lockcounter + 1
                    $currentHTMLNode = $htmlFileRow
                    $currentHTMLNode = $currentHTMLNode.Replace("Current_Serial", "$lockcounter")
                    $currentHTMLNode = $currentHTMLNode.Replace("ResourceGroupName", "$($rg.ResourceGroupName)")
                    $currentHTMLNode = $currentHTMLNode.Replace("LockName", "$($lock.name)")
                    $currentHTMLNode = $currentHTMLNode.Replace("LockLevel", "$($lock.Properties.level)")
                    $currentHTMLNode = $currentHTMLNode.Replace("Age", "$elaplsedDays")
                    $Report += $currentHTMLNode
                }
            }
            else {
                Write-Host "$counter. $($rg.ResourceGroupName) - $elaplsedDays days old. Will be kept."
            }
        }
        else {
            Write-Host "$counter. $($rg.ResourceGroupName) - Could not get resource group CreationTime. Will be removed."
            $cleanupRGs += $rg.ResourceGroupName
        }
    }
}

if ($RemoveAutoCleanupVMs) {
    foreach ($rg in $AutoClenaupVMs) {
        $counter += 1
        if ($rg.Tags.AutoCleanup -imatch "Disabled") {
            Write-Host "$counter. $($rg.ResourceGroupName) - AutoCleanup is '$($rg.Tags.AutoCleanup)'. Will be skipped."
        } else {
            if ($currentTimeStamp -gt [datetime]$rg.Tags.AutoCleanup) {
                Write-Host "$counter. $($rg.ResourceGroupName) - is beyond AutoCleanup date '$($rg.Tags.AutoCleanup)'. Will be removed."
                $cleanupRGs += $rg.ResourceGroupName
            } else {
                Write-Host "$counter. $($rg.ResourceGroupName) - is under AutoCleanup date '$($rg.Tags.AutoCleanup)'. Will be skipped."
            }
        }
    }
}

$cleanupRGScriptBlock = {
    $RGName = $args[0]
    $DryRun = $args[1]
    $RemoveDisks = $args[2]
    if (-not $DryRun) {
        if ($RemoveDisks) {
            $vms = Get-AzVM -ResourceGroupName $RGName
        }
        Remove-AzResourceGroup -Name $RGName -Verbose -Force

        if ($? -and $RemoveDisks) {
            foreach ($vm in $vms) {
                $osDiskUri = $vm.StorageProfile.OSDisk.Vhd.Uri
                #VHD URL example - http://storageaccountname.blob.core.windows.net/vhds/vhdname.vhd
                if ($osDiskUri) {
                    $osDiskContainerName = $osDiskUri.Split('/')[-2]
                    $osDiskStorageAcct = Get-AzStorageAccount | Where-Object { $_.StorageAccountName -eq $osDiskUri.Split('/')[2].Split('.')[0] }
                    Write-Host "Remove unmanaged OS disk $osDiskUri"
                    $osDiskStorageAcct | Remove-AzStorageBlob -Container $osDiskContainerName -Blob $osDiskUri.Split('/')[-1]
                } else {
                    Write-Host "Remove managed OS disk $($vm.StorageProfile.OsDisk.Name)"
                    Get-AzDisk -DiskName $vm.StorageProfile.OsDisk.Name  | Remove-AzDisk -Force
                }

                foreach ($dataDisk in $vm.StorageProfile.DataDisks) {
                    if ($dataDisk.Vhd.Uri) {
                        $dataDiskStorageAcct = Get-AzStorageAccount -Name $uri.Split('/')[2].Split('.')[0]
                        Write-Host "Remove unmanaged data disk $uri"
                        $dataDiskStorageAcct | Remove-AzStorageBlob -Container $uri.Split('/')[-2] -Blob $uri.Split('/')[-1]
                    }
                    if ($dataDisk.ManagedDisk) {
                        Write-Host "Remove managed data disk $($dataDisk.Name)"
                        Get-AzDisk -DiskName $dataDisk.Name  | Remove-AzDisk -Force
                    }
                }
            }
        }
    } else {
        Write-Host "DryRun Completed."
    }
}

foreach ($RGName in $cleanupRGs) {
    Write-Host "Triggering : Delete-ResourceGroup-$RGName..."
    $null = Start-Job -ScriptBlock $cleanupRGScriptBlock -ArgumentList @($RGName,$DryRun,$RemoveDisks) -Name "Delete-ResourceGroup-$RGName"
}
Write-Host "$($cleanupRGs.Count) resource groups are being removed..."

Write-Host "Checking background cleanup jobs.."
$cleanupJobList = Get-Job | Where-Object { $_.Name -imatch "Delete-ResourceGroup"}
$isAllCleaned = $false
while (!$isAllCleaned) {
    $runningJobsCount = 0
    $isAllCleaned = $true
    $cleanupJobList = Get-Job | Where-Object { $_.Name -imatch "Delete-ResourceGroup"}
    foreach ( $cleanupJob in $cleanupJobList ) {
        $jobStatus = Get-Job -Id $cleanupJob.ID
        if ( $jobStatus.State -ne "Running" ) {
            $tempRG = $($cleanupJob.Name).Replace("Delete-ResourceGroup-", "")
            Write-Host "$tempRG : Delete : $($jobStatus.State)"
            Receive-Job -Id $cleanupJob.ID
            Remove-Job -Id $cleanupJob.ID -Force
        }
        else {
            Write-Host "$($cleanupJob.Name) is running."
            $isAllCleaned = $false
            $runningJobsCount += 1
        }
    }
    if ($runningJobsCount -gt 0) {
        Write-Host "$runningJobsCount background cleanup jobs still running. Waiting 30 seconds..."
        Start-Sleep -Seconds 30
    }
}
Write-Host "All background cleanup jobs finished."

$Report += '</table>'
$FinalEmailSummary += $htmlFileStart
foreach ( $line in $Report.Split("`n")) {
    $FinalEmailSummary += $line
}

$FinalEmailSummary += '<p style="text-align: right;"><em><span style="font-size: 18px;"><span style="font-family: times new roman,times,serif;">&gt;</span></span></em></p>'
if ( $lockcounter -gt 0 ) {
    Set-Content -Path $FinalHtmlFile -Value $FinalEmailSummary
    Set-Content -Path $EmailSubjectTextFile -Value "VMs with Lock more than $LockedResourceAgeInDays Days at $($psttime.Year)/$($psttime.Month)/$($psttime.Day)"
}
