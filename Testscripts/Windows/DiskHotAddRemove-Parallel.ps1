# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
param([String] $TestParams, [object] $AllVMData)
$ErrorActionPreference = "Stop"
function Main {
    param (
        $TestParams, $AllVMData
    )
    $currentTestResult = Create-TestResultObject
    $resultArr = @()
    try {
        $testResult = $null
        $count = 0
        $diskSizeinGB = $TestParams.DiskSize
        $allDiskNames = @()
        $allUnmanagedDataDisks = @()
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
        Write-LogInfo "Parallel Addition of add max Data Disks [$diskCount] to the VM "
        While ($count -lt $diskCount) {
            $count += 1
            $diskName = "disk"+ $count.ToString()
            $allDiskNames += $diskName
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
                $allUnmanagedDataDisks += $dataDiskVhdUri.Split('/')[-1]
                Add-AzVMDataDisk -VM $virtualMachine -Name $diskName -VhdUri $dataDiskVhdUri -Caching None -DiskSizeInGB $diskSizeinGB -Lun ($count-1) -CreateOption Empty | Out-Null
            }
            Write-LogInfo "$count - Successfully create an empty data disks of size $diskSizeinGB GB"
        }
        Write-LogInfo "Number of data disks added to the VM $count"
        $updateVM1 = Update-AzVM -VM $virtualMachine -ResourceGroupName $AllVMData.ResourceGroupName
        if ($updateVM1.IsSuccessStatusCode) {
            Write-LogInfo "Successfully attached $count empty data disks of size $diskSizeinGB GB to VM"
        } else {
            $testResult = $resultFail
            throw "Fail to attach $count empty data disks of size $diskSizeinGB GB to VM"
        }
        Write-LogInfo "Verifying if data disks are added to the VM - running lsblk on remote VM"
        $retry = 1
        $retryMaxTimes = 5
        $osDiskLabel = Run-LinuxCmd -username $user -password $password -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -command ". utils.sh && get_OSdisk" -runAsSudo
        # retry here - it takes time to show all disks on the VM
        while ($retry -lt $retryMaxTimes) {
            $verifiedDiskCount = Run-LinuxCmd -username $user -password $password -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -command "lsblk -io KNAME,TYPE,SIZE,MODEL | grep -i 'Virtual Disk' | grep $diskSizeinGB | grep -v '$osDiskLabel ' | wc -l" -runAsSudo
            Write-LogInfo "Number of data disks verified inside VM $verifiedDiskCount, expected count is $diskCount"
            if ($verifiedDiskCount -eq $diskCount) {
                Write-LogInfo "Data disks added to the VM are successfully verified inside VM"
                break
            } else {
                Write-LogInfo "Retry times - $retry"
                Start-Sleep 30
                $retry = $retry + 1
            }
        }
        if ($retry -eq $retryMaxTimes) {
            $testResult=$resultFail
            throw "Data disks added to the VM failed to verify inside VM"
        }
        Write-LogInfo "Parallel Removal of Data Disks from the VM"
        Remove-AzVMDataDisk -VM $virtualMachine -DataDiskNames $allDiskNames | Out-Null
        $updateVM2 = Update-AzVM -VM $virtualMachine -ResourceGroupName $AllVMData.ResourceGroupName
        if ($updateVM2.IsSuccessStatusCode) {
            Write-LogInfo "Successfully removed the data disk from the VM"
        } else {
            throw "Failed to remove the data disk from the VM"
        }
        $osDiskLabel = Run-LinuxCmd -username $user -password $password -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -command ". utils.sh && get_OSdisk" -runAsSudo
        $finalDiskCount = Run-LinuxCmd -username $user -password $password -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -command "lsblk -io KNAME,TYPE,SIZE,MODEL | grep -i 'Virtual Disk' | grep $diskSizeinGB | grep -v '$osDiskLabel ' | wc -l" -runAsSudo
        if([int]$finalDiskCount -ne 0) {
            $testResult = $resultFail
            throw "Data disk is NOT removed from the VM successfully"
        }
        Write-LogInfo "Successfully verified that all data disks are removed from the VM"
        # Delete unmanaged data disks
        if (!$storageProfile.OsDisk.ManagedDisk) {
            foreach ($unmanagedDataDisk in $allUnmanagedDataDisks) {
                Write-LogInfo "Delete unmanaged data disks $unmanagedDataDisk"
                $osVhdStorageAccount | Remove-AzStorageBlob -Container $dataDiskVhdUri.Split('/')[-2] -Blob $unmanagedDataDisk -Verbose -Force
            }
        }
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
