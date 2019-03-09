# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Description
    It deploys the VM, verifies core number/memory size,
    then resize the VM, verifies new core number/memory size.
#>

param([object] $AllVMData)

function Main {
    $testResult = ""

    try {
        $testedVMSizes = @()   # The VM sizes have been tested
        $resizeVMSizeFailures = @()
        $testedVMSizes += $AllVMData.InstanceSize
        $previousVMSize = $AllVMData.InstanceSize

        $loadBalanceName = (Get-AzureRmLoadBalancer -ResourceGroupName $AllVMData.ResourceGroupName).Name
        $VirtualMachine = Get-AzureRmVM -ResourceGroupName $AllVMData.ResourceGroupName -Name $AllVMData.RoleName
        for ( $i = 0; $i -le 30; $i++ ) {
            $vmSizes = (Get-AzureRmVMSize -ResourceGroupName $AllVMData.ResourceGroupName -VMName $AllVMData.RoleName).Name
            Write-LogInfo "The VM can be resized to the following sizes: $vmSizes"
            foreach ($vmSize in $vmSizes) {
                # Load balancing is not supported for Basic VM sizes.
                if ($loadBalanceName -and ($vmSize -like "Basic*")) {
                    continue
                }
                if (!($vmSize -in $testedVMSizes)) {
                    break
                }
            }
            if ($vmSize -in $testedVMSizes) {
                break
            }
            $testedVMSizes += $vmSize

            Write-LogInfo "--------------------------------------------------------"
            Write-LogInfo "Resizing the VM to size: $vmSize"
            $VirtualMachine.HardwareProfile.VmSize = $vmSize
            Update-AzureRmVM -VM $VirtualMachine -ResourceGroupName $AllVMData.ResourceGroupName | Out-Null
            if ($?) {
                Write-LogInfo "Resize the VM from $previousVMSize to $vmSize successfully"
            } else {
                if ($error[0].ToString() -like "*SkuNotAvailable*") {
                    $i--
                    Write-LogInfo "The $vmSize is not supported by current subscription. Skip it."
                } else {
                    $resizeVMSizeFailures += "Resize the VM from $previousVMSize to $vmSize failed"
                    $testResult = "FAIL"
                    Write-LogErr "Resize the VM from $previousVMSize to $vmSize failed"
                }
                continue
            }

            # Add CPU count and memory checks
            $expectedVMSize = Get-AzureRmVMSize -Location $AllVMData.Location | Where-Object {$_.Name -eq $vmSize}
            $expectedCPUCount = $expectedVMSize.NumberOfCores
            $expectedMemorySizeInMB = $expectedVMSize.MemoryInMB
            $actualCPUCount = Run-LinuxCmd -username $user -password $password -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -command "nproc"
            $actualMemorySizeInKB = Run-LinuxCmd -username $user -password $password -ip $AllVMData.PublicIP -port $AllVMData.SSHPort   `
                                 -command "grep -i memtotal /proc/meminfo | awk '{ print `$`2 }'"
            $actualMemorySizeInMB = [math]::Truncate($actualMemorySizeInKB/1024)
            Write-LogInfo "Expected CPU Count: $expectedCPUCount"
            Write-LogInfo "Actual CPU Count: $actualCPUCount"
            Write-LogInfo "Expected Memory Size in MB: $expectedMemorySizeInMB"
            Write-LogInfo "Actual Memory Size in MB: $actualMemorySizeInMB"

            if ($expectedCPUCount -eq $actualCPUCount) {
                Write-LogInfo "CPU count verification is successful"
                if ($actualMemorySizeInMB -ne $expectedMemorySizeInMB) {
                    Write-LogWarn "Memory size within VM is NOT equal to the expected memory size"
                    if (($expectedMemorySizeInMB - $actualMemorySizeInMB)/$expectedMemorySizeInMB -ge 0.2) {
                        Write-LogErr "The diff between the expected memory and the actual memory is too large"
                        $testResult = "FAIL"
                        $resizeVMSizeFailures += "Memory check failed after resizing the VM from $previousVMSize to $vmSize"
                    }
                }
            } else {
                Write-LogErr "CPU count verification failed"
                $resizeVMSizeFailures += "CPU count verification failed after resizing the VM from $previousVMSize to $vmSize"
                $testResult = "FAIL"
            }
            $previousVMSize = $vmSize
        }

        # Resize the VM with an unsupported size in the current hardware cluster
        $allVMSize = (Get-AzureRmVMSize -Location $AllVMData.Location).Name
        foreach ($vmSize in $allVMSize) {
            if (!($vmSize -in $vmSizes)) {
                Write-LogInfo "--------------------------------------------------------"
                Write-LogInfo "Resizing the VM to size: $vmSize"
                $VirtualMachine.HardwareProfile.VmSize = $vmSize
                Update-AzureRmVM -VM $VirtualMachine -ResourceGroupName $AllVMData.ResourceGroupName | Out-Null
                if ($?) {
                    $testResult = "FAIL"
                    $resizeVMSizeFailures += "The VM should fail to resize from $previousVMSize to $vmSize"
                    Write-LogErr "The VM should fail to resize because the $vmSize is out of range."
                } else {
                    Write-LogInfo "Resize the VM with $vmSize failed. It's expected."
                }
                break
            }
        }

        if ($resizeVMSizeFailures.Count) {
            Write-LogInfo "The below are the summary failures during the test"
            foreach ($failure in $resizeVMSizeFailures) {
                Write-LogErr "$failure"
            }
        }
        if (!$testResult) {
            $testResult = "PASS"
        }
    } catch {
        $ErrorMessage = $_.Exception.Message
        $ErrorLine = $_.InvocationInfo.ScriptLineNumber
        Write-LogErr "EXCEPTION : $ErrorMessage at line: $ErrorLine"
    } finally {
        if (!$testResult) {
            $testResult = "Aborted"
        }
        $resultArr += $testResult
    }

    $currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
    return $currentTestResult.TestResult
}

Main