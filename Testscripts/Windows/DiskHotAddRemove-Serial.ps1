# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
param([String] $TestParams, [object] $AllVMData)
$ErrorActionPreference = "Stop"
function Main {
    param (
        $TestParams, $AllVMData
    )
    # Create test result
    $currentTestResult = Create-TestResultObject
    $resultArr = @()
    try {
        $testResult = $null
        $count = 0
        $diskSizeinGB = $TestParams.DiskSize
        $virtualMachine = Get-AzVM -ResourceGroupName $AllVMData.ResourceGroupName -Name $AllVMData.RoleName
        $azVmSize = Get-AzVMSize -Location $AllVMData.Location | Where-Object {$_.Name -eq $AllVMData.InstanceSize}
        if (!$azVmSize) {
            throw "Could not find VM Size information for $($AllVMData.InstanceSize)."
        }
        $diskCount = $azVmSize.MaxDataDiskCount
        if (!$diskCount -or $diskCount -eq 0) {
            throw "MaxDataDiskCount of current VM Size $($AllVMData.InstanceSize) is not acceptable."
        }
        $storageProfile = (Get-AzVM -ResourceGroupName $AllVMData.ResourceGroupName -Name $AllVMData.RoleName).StorageProfile
        Write-LogInfo "Serial Addition and Removal of max Data Disks [$diskCount] to the VM"
        $verifiedDiskCount = 0
        While ($count -lt $diskCount) {
            $count += 1
            $diskName = "disk"+ $count.ToString()
            if ($storageProfile.OsDisk.ManagedDisk) {
                # Add managed data disks
                $storageType = $TestParams.DiskSku
                $diskConfig = New-AzDiskConfig -SkuName $storageType -Location $AllVMData.Location -CreateOption Empty -DiskSizeGB $diskSizeinGB
                $dataDisk = New-AzDisk -DiskName $diskName -Disk $diskConfig -ResourceGroupName $AllVMData.ResourceGroupName
                Add-AzVMDataDisk -VM $virtualMachine -Name $diskName -CreateOption Attach -ManagedDiskId $dataDisk.Id -Lun ($count-1) | Out-Null
            } else {
                # Add unmanaged data disks
                $osVhdStorageAccountName = $storageProfile.OsDisk.Vhd.Uri.Split(".").split("/")[2]
                $randomString = "{0}{1}" -f $(-join ((97..122) | Get-Random -Count 6 | ForEach-Object {[char]$_})), $(Get-Random -Maximum 99 -Minimum 11)
                $dataDiskVhdUri = "http://${osVhdStorageAccountName}.blob.core.windows.net/vhds/test${randomString}.vhd"
                $osVhdStorageAccount = Get-AzStorageAccount | Where-Object { $_.StorageAccountName -eq $osVhdStorageAccountName }
                $allDataDiskVhdUri = ($osVhdStorageAccount | Get-AzStorageBlob -Container $dataDiskVhdUri.Split('/')[-2]).name
                if ($allDataDiskVhdUri -Contains $dataDiskVhdUri.Split('/')[-1]) {
                    $count -= 1
                    continue
                }
                Add-AzVMDataDisk -VM $virtualMachine -Name $diskName -VhdUri $dataDiskVhdUri -Caching None -DiskSizeInGB $diskSizeinGB -Lun ($count-1) -CreateOption Empty | Out-Null
            }
            $updateVM1 = Update-AzVM -VM $virtualMachine -ResourceGroupName $AllVMData.ResourceGroupName
            if ($updateVM1.IsSuccessStatusCode) {
                Write-LogInfo "$count - Successfully attached an empty data disk of size $diskSizeinGB GB to VM"
            } else {
                $testResult = $resultFail
                throw "Fail to attach an empty data disk of size $diskSizeinGB GB to VM"
            }
            Write-LogInfo "Verifying if data disk is added to the VM: Running fdisk on remote VM"
            $fdiskOutput = Run-LinuxCmd -username $user -password $password -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -command "/sbin/fdisk -l | grep /dev/sd" -runAsSudo
            foreach ($line in ($fdiskOutput.Split([Environment]::NewLine))) {
                if($line -imatch "Disk /dev/sd[a-z][a-z]|sd[c-z]:" -and [int64]($line.Split()[4]) -eq (([int64]($diskSizeinGB) * [int64]1073741824))) {
                    $verifiedDiskCount += 1
                    Write-LogInfo "$verifiedDiskCount data disk is successfully attached to the VM: $line"
                }
            }
            if ($verifiedDiskCount -eq 1) {
                Write-LogInfo "Data disk added to the VM is successfully verified inside VM"
            } else {
                $testResult = $resultFail
                throw "Data disk added to the VM failed to verify inside VM"
            }
            Write-LogInfo "Removing the Data Disks from the VM"
            Remove-AzVMDataDisk -VM $virtualMachine -DataDiskNames $diskName | Out-Null
            $updateVM2 = Update-AzVM -VM $virtualMachine -ResourceGroupName $AllVMData.ResourceGroupName
            if ($updateVM2.IsSuccessStatusCode) {
                Write-LogInfo "Successfully removed the data disk from the VM"
            } else {
                throw "Failed to remove the data disk from the VM"
            }
            Write-LogInfo "Verifying if data disk is removed from the VM: Running fdisk on remote VM"
            $fdiskFinalOutput = Run-LinuxCmd -username $user -password $password -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -command "/sbin/fdisk -l | grep /dev/sd" -runAsSudo
            foreach ($line in ($fdiskFinalOutput.Split([Environment]::NewLine))) {
                if($line -imatch "Disk /dev/sd[a-z][a-z]|sd[c-z]:" -and [int64]($line.Split()[4]) -eq (([int64]($diskSizeinGB) * [int64]1073741824))) {
                    $testResult = $resultFail
                    throw "Data disk is NOT removed from the VM at $line"
                }
            }
            Write-LogInfo "Successfully verified that data disk is removed from the VM"
            $verifiedDiskCount-=1
            # Remove unmanaged data disks
            if (!$storageProfile.OsDisk.ManagedDisk) {
                $osVhdStorageAccount | Remove-AzStorageBlob -Container $dataDiskVhdUri.Split('/')[-2] -Blob $dataDiskVhdUri.Split('/')[-1] -Verbose -Force
            }
        }
        Write-LogInfo "Successfully added and removed $diskCount number of data disks"
        $testResult = $resultPass
    } catch {
        $ErrorMessage = $_.Exception.Message
        $ErrorLine = $_.InvocationInfo.ScriptLineNumber
        Write-LogErr "$ErrorMessage at line: $ErrorLine"
    } finally {
        if (!$testResult) {
            $testResult = $resultAborted
        }
        $resultArr += $testResult
    }
    $currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
    return $currentTestResult.TestResult
}
Main -TestParams (ConvertFrom-StringData $TestParams.Replace(";","`n")) -AllVMData $AllVMData
