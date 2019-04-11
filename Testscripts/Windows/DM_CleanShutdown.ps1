# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
<#
.Synopsis
 Verify that a VM that looses memory shuts down gracefully.
 Description:
   Verify a VM that looses memory due to another VM starting shuts down cleanly.
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
       "Tries=3;enable=yes;minMem1=512MB;maxMem1=20%;startupMem1=20%;memWeight1=0;
       enable=yes;minMem2=512MB;maxMem2=80%;startupMem2=80%;memWeight2=100"
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
        $HvServer=$VM1.HyperVHost
        $VMPort=$VM2.SSHPort
        Set-VMDynamicMemory -VM $VM1 -minMem $TestParams.minMem1 -maxMem $TestParams.maxMem1 -startupMem $TestParams.startupMem1 -memWeight $memweight1 | Out-Null
        Set-VMDynamicMemory -VM $VM2 -minMem $TestParams.minMem2 -maxMem $TestParams.maxMem2 -startupMem $TestParams.startupMem2 -memWeight $memweight2 | Out-Null
        Write-LogInfo "Starting VM1 $VM1Name"
        $VM1Ipv4=Start-VMandGetIP $VM1Name $HvServer $VMPort $user $password
        Write-LogInfo "IP of $VM1Name is $VM1Ipv4"
        # Change working directory to root dir
        Set-Location $WorkingDirectory
        if ($tries -le 0) {
            $tries = $defaultTries
        }
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
        $VM2Ipv4=Start-VMandGetIP $VM2Name $HvServer $VMPort $user $password
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
        Stop-VM -vmName $VM1Name -ComputerName $HvServer -force
        if (-not $?) {
            throw "$VM1Name did not shutdown via Hyper-V"
        }
        # vm1 shut down gracefully via Hyper-V, so shutdown vm2
        Stop-VM -vmName $VM2Name -ComputerName $HvServer -force
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
