# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
param([String] $TestParams, [object] $AllVMData)
$ErrorActionPreference = "Stop"
function Main {
    param (
        $TestParams,$AllVMData
    )
    $currentTestResult = Create-TestResultObject
    $resultArr = @()
    try {
        $testResult = $null
        $diskSizeinGB=$TestParams.DiskSize
        $allDiskNames = @()
        $VirtualMachine = Get-AzureRmVM -ResourceGroupName $AllVMData.ResourceGroupName -Name $AllVMData.RoleName
        $diskCount = (Get-AzureRmVMSize -Location $AllVMData.Location | Where-Object {$_.Name -eq $AllVMData.InstanceSize}).MaxDataDiskCount
        Write-LogInfo "Parallel Addition of Data Disks to the VM "
        While($count -lt $diskCount) {
            $count += 1
            $diskName = "disk"+ $count.ToString()
            $allDiskNames += $diskName
            $StorageType = 'Premium_LRS'
            $diskConfig = New-AzureRmDiskConfig -SkuName $StorageType -Location $AllVMData.Location -CreateOption Empty -DiskSizeGB $diskSizeinGB
            $dataDisk = New-AzureRmDisk -DiskName $diskName -Disk $diskConfig -ResourceGroupName $AllVMData.ResourceGroupName
            Write-LogInfo "Adding an empty data disk of size $diskSizeinGB GB"
            $sts=Add-AzureRmVMDataDisk -VM $VirtualMachine -Name $diskName -CreateOption Attach -ManagedDiskId $dataDisk.Id -Lun $count
            if($sts.ProvisioningState -eq "Succeeded") {
                Write-LogInfo "Successfully created an empty data disk of size $diskSizeinGB GB"
            }
            else {
                $testResult = $resultFail
                throw "Failed to create an empty data disk of size $diskSizeinGB GB"
            }
        }
        Write-LogInfo "Number of data disks added to the VM $count"
        Update-AzureRMVM -VM $VirtualMachine -ResourceGroupName $AllVMData.ResourceGroupName
        Write-LogInfo "Successfully added $diskCount empty data disks to the VM"
        Write-LogInfo "Verifying if data disk is added to the VM: Running fdisk on remote VM"
        $fdiskOutput = Run-LinuxCmd -username $user -password $password -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -command "/sbin/fdisk -l | grep /dev/sd" -runAsSudo
        foreach($line in ($fdiskOutput.Split([Environment]::NewLine))) {
            if($line -imatch "Disk /dev/sd[^ab]:" -and [int64]($line.Split()[4]) -eq (([int64]($diskSizeinGB) * [int64]1073741824))){
                Write-LogInfo "Data disk is successfully mounted to the VM: $line"
                $verifiedDiskCount += 1
            }
        }
        Write-LogInfo "Number of data disks verified inside VM $verifiedDiskCount"
        if($verifiedDiskCount -ge $diskCount) {
            Write-LogInfo "Data disks added to the VM are successfully verified inside VM"
        }
        else {
            $testResult=$resultFail
            throw "Data disks added to the VM failed to verify inside VM"
        }
        Write-LogInfo "Parallel Removal of Data Disks from the VM"
        $sts=Remove-AzureRmVMDataDisk -VM $VirtualMachine -DataDiskNames $allDiskNames
        if($sts.ProvisioningState -eq "Succeeded") {
            Write-LogInfo "Successfully removed the data disk from the VM"
        }
        else {
            throw "Failed to remove data disk"
        }
        Update-AzureRMVM -VM $VirtualMachine -ResourceGroupName $AllVMData.ResourceGroupName
        Write-LogInfo "Verifying if data disks are removed from the VM: Running fdisk on remote VM"
        $fdiskFinalOutput = Run-LinuxCmd -username $user -password $password -ip  $AllVMData.PublicIP -port $AllVMData.SSHPort -command "/sbin/fdisk -l | grep /dev/sd" -runAsSudo
        foreach($line in ($fdiskFinalOutput.Split([Environment]::NewLine))) {
            if($line -imatch "Disk /dev/sd[^ab]:" -and [int64]($line.Split()[4]) -eq (([int64]($diskSizeinGB) * [int64]1073741824))) {
                $testResult=$resultFail
                throw "Data disk is NOT removed from the VM at $line"
            }
        }
        Write-LogInfo "Successfully verified that all data disks are removed from the VM"
        $testResult=$resultPass
    } catch {
        $ErrorMessage =  $_.Exception.Message
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
