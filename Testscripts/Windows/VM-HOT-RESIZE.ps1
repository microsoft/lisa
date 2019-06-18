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

        $loadBalanceName = (Get-AzLoadBalancer -ResourceGroupName $AllVMData.ResourceGroupName).Name
        $VirtualMachine = Get-AzVM -ResourceGroupName $AllVMData.ResourceGroupName -Name $AllVMData.RoleName
        $ComputeSKUs = Get-AzComputeResourceSku
        foreach ($param in $currentTestData.TestParameters.param) {
            if ($param -match "TestMode") {
                $testMode = $param.Replace("TestMode=","").Replace('"',"")
            }
        }
        if ($testMode -eq "economy") {
            Write-LogInfo "The test mode is economy mode"
            $totalTestTimes = 10
        } else {
            $totalTestTimes = (Get-AzVMSize -Location $AllVMData.Location).Length
        }

        for ($i = 0; $i -le $totalTestTimes; $i++) {
            $vmSizes = (Get-AzVMSize -ResourceGroupName $AllVMData.ResourceGroupName -VMName $AllVMData.RoleName).Name
            # For economy mode, select a size by random in order to cover as many different serial sizes as possible
            if ($testMode -eq "economy") {
                $vmSizes = $vmSizes | Get-Random -Count 1
                if ($loadBalanceName -and ($vmSizes -like "Basic*")) {
                    continue
                }
            }

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
                continue
            }
            $Restrictions = ($ComputeSKUs | Where-Object { $_.Locations -eq $AllVMData.Location -and $_.ResourceType -eq "virtualMachines" `
                -and $_.Name -eq $vmSize}).Restrictions
            if ( ($Restrictions | Where-Object {$_.Type -eq "Location"}).ReasonCode -eq "NotAvailableForSubscription") {
                $i--
                Write-LogInfo "The $vmSize is not supported by current subscription. Skip it."
                break
            }
            $testedVMSizes += $vmSize

            Write-LogInfo "--------------------------------------------------------"
            Write-LogInfo "Resizing the VM to size: $vmSize"
            $VirtualMachine.HardwareProfile.VmSize = $vmSize
            Update-AzVM -VM $VirtualMachine -ResourceGroupName $AllVMData.ResourceGroupName | Out-Null
            if ($?) {
                Write-LogInfo "Resize the VM from $previousVMSize to $vmSize successfully"
            } else {
                $resizeVMSizeFailures += "Resize the VM from $previousVMSize to $vmSize failed"
                $testResult = "FAIL"
                Write-LogErr "Resize the VM from $previousVMSize to $vmSize failed"
                continue
            }

            # Add CPU count and memory checks
            $expectedVMSize = Get-AzVMSize -Location $AllVMData.Location | Where-Object {$_.Name -eq $vmSize}
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
        $allVMSize = (Get-AzVMSize -Location $AllVMData.Location).Name
        $vmSizes = (Get-AzVMSize -ResourceGroupName $AllVMData.ResourceGroupName -VMName $AllVMData.RoleName).Name
        foreach ($vmSize in $allVMSize) {
            $Restrictions = ($ComputeSKUs | Where-Object { $_.Locations -eq $AllVMData.Location -and $_.ResourceType -eq "virtualMachines" `
                -and $_.Name -eq $vmSize}).Restrictions
            if ( ($Restrictions | Where-Object {$_.Type -eq "Location"}).ReasonCode -eq "NotAvailableForSubscription") {
                Write-LogInfo "The $vmSize is not supported by current subscription. Skip it."
                break
            }
            if (!($vmSize -in $vmSizes)) {
                Write-LogInfo "--------------------------------------------------------"
                Write-LogInfo "Resizing the VM to size: $vmSize"
                $VirtualMachine.HardwareProfile.VmSize = $vmSize
                Update-AzVM -VM $VirtualMachine -ResourceGroupName $AllVMData.ResourceGroupName | Out-Null
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
