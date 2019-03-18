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
        $diskSizeinGB = $TestParams.DiskSize
        $VirtualMachine = Get-AzureRmVM -ResourceGroupName $AllVMData.ResourceGroupName -Name $AllVMData.RoleName
        $diskCount = (Get-AzureRmVMSize -Location $AllVMData.Location | Where-Object {$_.Name -eq $AllVMData.InstanceSize}).MaxDataDiskCount
        Write-LogInfo "Serial Addition and Removal of Data Disks"
        While ($count -lt $diskCount) {
            $count += 1
            $verifiedDiskCount = 0
            $diskName = "disk"+ $count.ToString()
            $storageType = 'Premium_LRS'
            $diskConfig = New-AzureRmDiskConfig -SkuName $storageType -Location $AllVMData.Location -CreateOption Empty -DiskSizeGB $diskSizeinGB
            $dataDisk = New-AzureRmDisk -DiskName $diskName -Disk $diskConfig -ResourceGroupName $AllVMData.ResourceGroupName
            $sts1 = Add-AzureRmVMDataDisk -VM $VirtualMachine -Name $diskName -CreateOption Attach -ManagedDiskId $dataDisk.Id -Lun $count
            if ($sts1.ProvisioningState -eq "Succeeded") {
                Write-LogInfo "Successfully created an empty data disk of size $diskSizeinGB GB"
            } else {
                $testResult = $resultFail
                throw "Failed to create an empty data disk of size $diskSizeinGB GB"
            }
            Update-AzureRMVM -VM $VirtualMachine -ResourceGroupName $AllVMData.ResourceGroupName | Out-Null
            Write-LogInfo "Verifying if data disk is added to the VM: Running fdisk on remote VM"
            $fdiskOutput = Run-LinuxCmd -username $user -password $password -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -command "/sbin/fdisk -l | grep /dev/sd" -runAsSudo
            foreach ($line in ($fdiskOutput.Split([Environment]::NewLine))) {
                if($line -imatch "Disk /dev/sd[^ab]:" -and [int64]($line.Split()[4]) -eq (([int64]($diskSizeinGB) * [int64]1073741824))) {
                    Write-LogInfo "Data disk is successfully mounted to the VM: $line"
                    $verifiedDiskCount += 1
                }
            }
            if ($verifiedDiskCount -eq 1) {
                Write-LogInfo "Data disk added to the VM is successfully verified inside VM"
            } else {
                $testResult = $resultFail
                throw "Data disk added to the VM failed to verify inside VM"
            }
            Write-LogInfo "Removing the Data Disks from the VM"
            $sts3 = Remove-AzureRmVMDataDisk -VM $VirtualMachine -DataDiskNames $diskName
            if ($sts3.ProvisioningState -eq "Succeeded") {
                Write-LogInfo "Successfully removed data disk"
            } else {
                throw "Failed to remove data disk"
            }
            Update-AzureRMVM -VM $VirtualMachine -ResourceGroupName $AllVMData.ResourceGroupName | Out-Null
            Write-LogInfo "Successfully removed the data disk from the VM"
            Write-LogInfo "Verifying if data disk is removed from the VM: Running fdisk on remote VM"
            $fdiskFinalOutput = Run-LinuxCmd -username $user -password $password -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -command "/sbin/fdisk -l | grep /dev/sd" -runAsSudo
            foreach ($line in ($fdiskFinalOutput.Split([Environment]::NewLine))) {
                if($line -imatch "Disk /dev/sd[^ab]:" -and [int64]($line.Split()[4]) -eq (([int64]($diskSizeinGB) * [int64]1073741824))) {
                    $testResult = $resultFail
                    throw "Data disk is NOT removed from the VM at $line"
                }
            }
            Write-LogInfo "Successfully verified that data disk is removed from the VM"
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
