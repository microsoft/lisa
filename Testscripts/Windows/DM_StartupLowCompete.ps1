# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
<#
.Synopsis
 Verify that a VM with low memory pressure looses memory when another VM has a high memory demand.
 Description:
   Verify a VM with low memory pressure and lots of memory looses memory when a starved VM has a
   high memory demand.
   2 VMs are required for this test.
   The testParams have the format of:
      vmName=Name of a VM, enable=[yes|no], minMem= (decimal) [MB|GB|%], maxMem=(decimal) [MB|GB|%],
      startupMem=(decimal) [MB|GB|%], memWeight=(0 < decimal < 100)
   Only the vmName param is taken into consideration. This needs to appear at least twice for
   the test to start.
      Tries=(decimal)
       This controls the number of times the script tries to start the second VM. If not set, a default
       value of 3 is set.
       This is necessary because Hyper-V usually removes memory from a VM only when a second one applies pressure.
       However, the second VM can fail to start while memory is removed from the first.
       There is a 30 second timeout between tries, so 3 tries is a conservative value.
   The following is an example of a testParam for configuring Dynamic Memory
       "Tries=3;VM1Name=ICA-HG*-role-0;enable=yes;minMem1=1024MB;maxMem1=80%;startupMem1=80%;memWeight1=0;
       VM2Name=ICA-HG*-role-1;enable=yes;minMem2=1024MB;maxMem2=50%;startupMem2=40%;memWeight2=0"
   All scripts must return a boolean to indicate if the script completed successfully or not.
#>
param([String] $TestParams,
      [object] $AllVmData)
function Main {
    param (
        $VM1,
        $VM2,
        $TestParams
    )
    $currentTestResult = Create-TestResultObject
    $resultArr = @()
    try {
        $testResult = $null
        $memweight1=$TestParams.memWeight1
        $memweight2=$TestParams.memWeight2
        $VM1Name=$VM1.RoleName
        $VM2Name=$VM2.RoleName
        $VM1Ipv4=$VM1.PublicIP
        $VM2Ipv4=$VM2.PublicIP
        $HvServer=$VM1.HyperVHost
        $VMPort=$VM2.SSHPort
        Set-VMDynamicMemory -VM $VM1 -minMem $TestParams.minMem1 -maxMem $TestParams.maxMem1 -startupMem $TestParams.startupMem1 -memWeight $memweight1 | Out-Null
        Set-VMDynamicMemory -VM $VM2 -minMem $TestParams.minMem2 -maxMem $TestParams.maxMem2 -startupMem $TestParams.startupMem2 -memWeight $memweight2 | Out-Null
        Write-LogInfo "Starting VM1 $VM1Name"
        $VM1Ipv4=Start-VMandGetIP $VM1Name $HvServer $VMPort $user $password
        Write-LogInfo "IP of $VM1Name is $VM1Ipv4"
        # Change working directory to root dir
        Set-Location $WorkingDirectory
        $vm1 = Get-VM -Name $VM1Name -ComputerName $HvServer -ErrorAction SilentlyContinue
        $vm2 = Get-VM -Name $VM2Name -ComputerName $HvServer -ErrorAction SilentlyContinue
        # sleep 1 minute for VM to start reporting demand
        $sleepPeriod = 60
        while ($sleepPeriod -gt 0) {
            # get VM1's Memory
            [int64]$vm1BeforeAssigned = ($vm1.MemoryAssigned/[int64]1048576)
            [int64]$vm1BeforeDemand = ($vm1.MemoryDemand/[int64]1048576)
            if ($vm1BeforeAssigned -gt 0 -and $vm1BeforeDemand -gt 0) {
                break
            }
            $sleepPeriod -= 5
            Start-Sleep -s 5
        }
        Write-LogInfo "VM1 $VM1Name before assigned memory : $vm1BeforeAssigned"
        Write-LogInfo "VM1 $VM1Name before memory demand: $vm1BeforeDemand"
        if ($vm1BeforeAssigned -le 0) {
            throw "$VM1Name Assigned memory is 0"
        }
        if ($vm1BeforeDemand -le 0) {
            throw "$VM1Name Memory demand is 0"
        }
        Start-Sleep -s 100
        Write-LogInfo "Starting VM2 $VM2Name"
        $VM1Ipv4 = Start-VMandGetIP $VM2Name $HvServer $VMPort $user $password
        Write-LogInfo "IP of $VM2Name is $VM2Ipv4"
        # get VM1's Memory
        [int64]$vm1AfterAssigned = ($vm1.MemoryAssigned/[int64]1048576)
        [int64]$vm1AfterDemand = ($vm1.MemoryDemand/[int64]1048576)
        Write-LogInfo "VM1 $VM1Name after assigned memory : $vm1AfterAssigned"
        Write-LogInfo "VM1 $VM1Name after memory demand: $vm1AfterDemand"
        if ($vm1AfterAssigned -le 0) {
            throw "$VM1Name Assigned memory is 0 after $VM2Name started"
        }
        if ($vm1AfterDemand -le 0) {
            throw "$VM1Name Memory demand is 0 after $VM1Name started"
        }
        # Compute deltas
        [int64]$vm1AssignedDelta = [int64]$vm1BeforeAssigned - [int64]$vm1AfterAssigned
        [int64]$vm1DemandDelta = [int64]$vm1BeforeDemand - [int64]$vm1AfterDemand
        Write-LogInfo "Deltas after vm2 $VM2Name started"
        Write-LogInfo "VM1 $VM1Name Assigned : ${vm1AssignedDelta}"
        Write-LogInfo "VM1 $VM1Name Demand   : ${vm1DemandDelta}"
        # Assigned memory needs to have lowered after VM2 starts.
        if ($vm1AssignedDelta -le 0) {
            throw "VM1 $VM1Name did not lower its assigned Memory after VM2 $VM2Name started."
        }
        # sleep another 2 minute trying to get VM2's memory demand
        $sleepPeriod = 120 #seconds
        # get VM2's Memory
        while ($sleepPeriod -gt 0) {
            [int64]$vm2BeforeAssigned = ($vm2.MemoryAssigned/[int64]1048576)
            [int64]$vm2BeforeDemand = ($vm2.MemoryDemand/[int64]1048576)
            if ($vm2BeforeAssigned -gt 0 -and $vm2BeforeDemand -gt 0) {
                break
            }
            $sleepPeriod-= 5
            Start-Sleep -s 5
        }
        Write-LogInfo "VM2 $VM2Name before assigned memory : $vm2BeforeAssigned"
        Write-LogInfo "VM2 $VM2Name before memory demand: $vm2BeforeDemand"
        if ($vm2BeforeAssigned -le 0) {
            throw "$VM2Name Assigned memory is 0"
        }
        if ($vm2BeforeDemand -le 0) {
            throw "$VM2Name demand memory is 0"
        }
        # sleep 120 seconds to let VM2 stabilize
        Start-Sleep -s 120
        # get VM2's Memory
        [int64]$vm2AfterAssigned = ($vm2.MemoryAssigned/[int64]1048576)
        [int64]$vm2AfterDemand = ($vm2.MemoryDemand/[int64]1048576)
        Write-LogInfo "VM2 $VM2Name after assigned memory : $vm2AfterAssigned"
        Write-LogInfo "VM2 $VM2Name after memory demand: $vm2AfterDemand"
        if ($vm2AfterAssigned -le 0) {
            throw "$VM2Name Assigned memory is 0 after it stabilized"
        }
        if ($vm2AfterDemand -le 0) {
            throw "$VM2Name Memory demand is 0 after it stabilized"
        }
        # Compute deltas
        [int64]$vm2AssignedDelta = [int64]$vm2BeforeAssigned - [int64]$vm2AfterAssigned
        [int64]$vm2DemandDelta = [int64]$vm2BeforeDemand - [int64]$vm2AfterDemand
        Write-LogInfo "Deltas VM2 $VM2Name after it stabilized"
        Write-LogInfo "VM2 $VM2Name Assigned : ${vm2AssignedDelta}"
        Write-LogInfo "VM2 $VM2Name Demand   : ${vm2DemandDelta}"
        # get VM1's Memory
        [int64]$vm1EndAssigned = ($vm1.MemoryAssigned/[int64]1048576)
        [int64]$vm1EndDemand = ($vm1.MemoryDemand/[int64]1048576)
        Write-LogInfo "VM1 $VM1Name end assigned memory : $vm1EndAssigned"
        Write-LogInfo "VM1 $VM1Name end memory demand: $vm1EndDemand"
        if ($vm1EndAssigned -le 0) {
            throw "$VM1Name Assigned memory is 0 after VM2 $VM1Name stabilized"
        }
        if ($vm1EndDemand -le 0) {
            throw "$VM1Name Memory demand is 0 after VM2 $VM1Name stabilized"
        }
        # Compute deltas
        [int64]$vm1AssignedDelta = [int64]$vm1EndAssigned - [int64]$vm1AfterAssigned
        [int64]$vm1DemandDelta =  [int64]$vm1EndDemand - [int64]$vm1AfterDemand
        Write-LogInfo "Deltas VM1 $VM1Name after it stabilized"
        Write-LogInfo "VM1 $VM1Name Assigned : ${vm1AssignedDelta}"
        Write-LogInfo "VM1 $VM1Name Demand   : ${vm1DemandDelta}"
        $testResult = $resultPass
    }
    catch {
        $ErrorMessage =  $_.Exception.Message
        $ErrorLine = $_.InvocationInfo.ScriptLineNumber
        Write-LogErr "$ErrorMessage at line: $ErrorLine"
    }
    finally {
        if (!$testResult) {
            $testResult = "ABORTED"
        }
            $resultArr += $testResult
    }
    $currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
	return $currentTestResult.TestResult

}
Main -VM1 $allVMData[0] -VM2 $allVMData[1] -TestParams (ConvertFrom-StringData $TestParams.Replace(";","`n"))
