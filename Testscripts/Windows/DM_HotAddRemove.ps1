# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
<#
.Synopsis
 Verify that the assigned memory never exceeds the VMs Maximum Memory setting.

 Description:
   Using a VM with dynamic memory enabled, verify the assigned memory never exceeds the VMs Maximum Memory setting.
   Expected result: VM2’s memory mustn't exceed the Maximum Memory setting.

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

       "Tries=3;VM1Name=ICA-HG*-role-0;enable=yes;minMem1=1024MB;maxMem1=40%;startupMem1=512MB;memWeight1=100;
       VM2Name=ICA-HG*-role-1;enable=yes;minMem2=1024MB;maxMem2=85%;startupMem2=80%;memWeight2=0"

   All scripts must return a boolean to indicate if the script completed successfully or not.
#>
param([String] $TestParams,
      [object] $AllVmData)
#######################################################################
#
# Main script body
#
#######################################################################
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
        $HvServer=$VM1.HyperVHost
        $VMPort=$VM2.SSHPort
        $appGitURL = $TestParams.appGitURL
        $appGitTag = $TestParams.appGitTag
        # Change working directory to root dir
        Set-Location $WorkingDirectory
        Set-VMDynamicMemory -VM $VM1 -minMem $TestParams.minMem1 -maxMem $TestParams.maxMem1 -startupMem $TestParams.startupMem1 -memWeight $memweight1 | Out-Null
        Set-VMDynamicMemory -VM $VM2 -minMem $TestParams.minMem2 -maxMem $TestParams.maxMem2 -startupMem $TestParams.startupMem2 -memWeight $memweight2 | Out-Null
        Write-LogInfo "Starting VM1 $VM1Name"
        $VM1Ipv4 = Start-VMandGetIP $VM1Name $HvServer $VMPort $user $password
        $vm1 = Get-VM -Name $VM1Name -ComputerName $HvServer -ErrorAction SilentlyContinue
        $vm2 = Get-VM -Name $VM2Name -ComputerName $HvServer -ErrorAction SilentlyContinue
        # Check if stress-ng is installed
        Write-LogInfo "Checking if stress-ng is installed"
        $retVal1 = Publish-App "stress-ng" $VM1Ipv4 $appGitURL $appGitTag $VMPort
        if (-not $retVal1) {
            throw "stress-ng is not installed for VM1! Please install it before running the memory stress tests."
        }
        Write-LogInfo "stress-ng is installed! Will begin running memory stress tests shortly."
        $timeoutStress = 0
        Write-LogInfo "Starting VM2 $VM2Name"
        Start-VMandGetIP $VM2Name $HvServer $VMPort $user $password
        # get memory stats from vm1 and vm2
        # wait up to 2 min for it
        $sleepPeriod = 120 #seconds
        # get VM1 and VM2's Memory
        while ($sleepPeriod -gt 0) {
            [int64]$vm1BeforeAssigned = ($vm1.MemoryAssigned/1MB)
            [int64]$vm1BeforeDemand = ($vm1.MemoryDemand/1MB)
            [int64]$vm2BeforeAssigned = ($vm2.MemoryAssigned/1MB)
            [int64]$vm2BeforeDemand = ($vm2.MemoryDemand/1MB)
            if ($vm1BeforeAssigned -gt 0 -and $vm1BeforeDemand -gt 0 -and $vm2BeforeAssigned -gt 0 -and $vm2BeforeDemand -gt 0) {
                break
            }
            $sleepPeriod-= 5
            Start-Sleep -s 5
        }
        Write-LogInfo "Memory stats after both $VM1Name and $VM2Name started reporting "
        Write-LogInfo "$VM1Name : assigned - $vm1BeforeAssigned | demand - $vm1BeforeDemand"
        Write-LogInfo "$VM2Name : assigned - $vm2BeforeAssigned | demand - $vm2BeforeDemand"
        if (($vm1BeforeAssigned -le 0) -or ($vm1BeforeDemand -le 0) -or ($vm2BeforeAssigned -le 0) -or ($vm2BeforeDemand -le 0)) {
            throw "VM1 or VM2 reported 0 memory (assigned or demand)."
        }
        # Calculate the amount of memory to be consumed on VM1 and VM2 with stress-ng
        [int64]$vm1ConsumeMem = (Get-VMMemory -VMName $VM1Name -ComputerName $HvServer).Maximum
        # transform to MB
        $vm1ConsumeMem /= 1MB
        $duration = 420
        $chunks=0
        # Send Command to consume
        $cmdAddConstants = "echo -e `"timeoutStress=$($timeoutStress)\nmemMB=$($vm1ConsumeMem)\nduration=$($duration)\nchunk=$($chunks)`" > /home/$user/constants.sh"
        Run-LinuxCmd -username $user -password $password -ip $VM1Ipv4 -port $VMPort -command $cmdAddConstants -runAsSudo
        $Memcheck = "echo '${password}' | sudo -S -s eval `"export HOME=``pwd``;. utils.sh && UtilsInit && ConsumeMemory`""
        $job1=Run-LinuxCmd -username $user -password $password -ip $VM1Ipv4 -port $VMPort -command $Memcheck -runAsSudo -RunInBackGround
        if (-not $?) {
            throw "Unable to start job for creating pressure on $VM1Name"
        }
        # sleep a few seconds so all stress-ng processes start and the memory assigned/demand gets updated
        Start-Sleep -s 400
        # get memory stats for vm1 after stress-ng starts
        [int64]$vm1Assigned = ($vm1.MemoryAssigned/1MB)
        [int64]$vm1Demand = ($vm1.MemoryDemand/1MB)
        [int64]$vm2Assigned = ($vm2.MemoryAssigned/1MB)
        [int64]$vm2Demand = ($vm2.MemoryDemand/1MB)
        Write-LogInfo "Memory stats after $VM1Name started stress-ng"
        Write-LogInfo "$VM1Name : assigned - $vm1Assigned | demand - $vm1Demand"
        Write-LogInfo "$VM2Name : assigned - $vm2Assigned | demand - $vm2Demand"
        if (($vm1Demand -le $vm1BeforeDemand) -or ($vm1Assigned -le $vm1BeforeAssigned)) {
            throw "Memory Demand or Assignation on $VM1Name did not increase after starting stress-ng"
        }
        if ($vm2Assigned -ge $vm2BeforeAssigned) {
            throw "Memory Demand on $VM2Name did not decrease after starting stress-ng"
        }
        # Wait for jobs to finish now and make sure they exited successfully
        $totalTimeout = $timeout = 340
        $firstJobStatus = $false
        while ($timeout -gt 0) {
            if ($job1.State -like "Completed") {
                $firstJobStatus = $true
                $retVal = Receive-Job $job1
                if (-not $retVal) {
                    throw "Consume Memory script returned false on VM1 $VM1Name"
                }
                $diff = $totalTimeout - $timeout
                Write-LogInfo "Job finished in $diff seconds"
            }
            if ($firstJobStatus) {
                break
            }
            $timeout -= 1
            Start-Sleep -s 1
        }
        # stop vm2
        Stop-VM -VMName $VM2Name -ComputerName $HvServer -force
        # Verify if errors occured on guest
        $isAlive = Wait-ForVMToStartKVP $VM1Name $HvServer 10
        if (-not $isAlive) {
            throw "VM $VM2Name is unresponsive after running the memory stress test"
        }
        # Everything ok
        Write-LogInfo  "Memory Hot Add/Remove completed successfully"
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
