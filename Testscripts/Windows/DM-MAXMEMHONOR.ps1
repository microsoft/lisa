# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Synopsis
 Verify that the assigned memory never exceeds the VMs Maximum Memory setting.

 Description:
   Using a VM with dynamic memory enabled, verify the assigned memory never exceeds the VMs Maximum Memory setting.
   Expected result: VM2's memory must not exceed the Maximum Memory setting.

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

       "Tries=3;VM1Name=ICA-HG*-role-0;enable=yes;minMem=512MB;maxMem=80%;startupMem=80%;memWeight=0;
       VM2Name=ICA-HG*-role-1;enable=yes;minMem1=512MB;maxMem1=25%;startupMem1=25%;memWeight1=0"

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
        $memweight = $TestParams.memWeight
        $memweight1 = $TestParams.memWeight1
        $minMem = $TestParams.minMem
        $minMem1 = $TestParams.minMem1
        $maxMem = $TestParams.maxMem
        $maxMem1 = $TestParams.maxMem1
        $startupMem = $TestParams.startupMem
        $startupMem1 = $TestParams.startupMem1
        $VM1Ipv4 = $VM1.PublicIP
        $VMPort = $VM2.SSHPort
        $vm1name = $VM1.RoleName
        $vm2name = $VM2.RoleName
        $HvServer = $VM1.HyperVHost
        $appGitURL = $TestParams.appGitURL
        $appGitTag = $TestParams.appGitTag
        Write-LogInfo "VM1name is $vm1name"
        Write-LogInfo "VM2name is $vm2name"
        Write-LogInfo "Hvserver is $HvServer"
        Write-LogInfo "appGitURL is  $appGitURL"
        Write-LogInfo "appGitTag is  $appGitTag"
        Write-LogInfo "Param vm1 Details are -VM $VM1 -minMem $minMem -maxMem $TestParams.maxMem -startupMem $TestParams.startupMem -memWeight $memWeight"
        Write-LogInfo "Param vm2 Details are -VM $VM2 -minMem $minMem1 -maxMem $maxMem1 -startupMem $TestParams.startupMem1 -memWeight $memWeight1"
        Set-VMDynamicMemory -VM $VM1 -minMem $minMem -maxMem $maxMem -startupMem $startupMem -memWeight $TestParams.memWeight | Out-Null
        Set-VMDynamicMemory -VM $VM2 -minMem $minMem1 -maxMem $maxMem1 -startupMem $startupMem1 -memWeight $TestParams.memWeight1 | Out-Null
        Write-LogInfo "Starting VM1 $vm1name"
        $VM1Ipv4 = Start-VMandGetIP $vm1name $HvServer $VMPort $user $password
        # change working directory to root dir
        Set-Location $WorkingDirectory
        if (-not $WorkingDirectory) {
            throw "INFO : Mandatory param RootDir=Path; not found!"
        }
        $vm1 = Get-VM -Name $vm1name -ComputerName $HvServer -ErrorAction SilentlyContinue
        $vm2 = Get-VM -Name $vm2name -ComputerName $HvServer -ErrorAction SilentlyContinue
        # Check if stress-ng is installed
        Write-LogInfo "Checking if stress-ng is installed"
        $retVal1 = Publish-App "stress-ng" $VM1Ipv4 $appGitURL $appGitTag $VMPort
        if (-not $retVal1) {
            throw "stress-ng is not installed for VM1! Please install it before running the memory stress tests."
        }
        Write-LogInfo "stress-ng is installed! Will begin running memory stress tests shortly."
        $timeoutStress = 0
        Write-LogInfo "Starting VM2 $vm2Name"
        $VM2Ipv4 = Start-VMandGetIP $vm2name $HvServer $VMPort $user $password
        Write-LogInfo "IP for the VM $vm2name is $VM2Ipv4"
        # get memory stats from vm1 and vm2
        # wait up to 2 min for it
        $sleepPeriod = 120 #seconds
        # get VM1 and VM2's Memory
        while ($sleepPeriod -gt 0) {
            [int64]$vm1BeforeAssigned = ($vm1.MemoryAssigned/1MB)
            [int64]$vm1BeforeDemand = ($vm1.MemoryDemand/1MB)
            [int64]$vm2BeforeAssigned = ($vm2.MemoryAssigned/1MB)
            [int64]$vm2BeforeDemand = ($vm2.MemoryDemand/1MB)
            if ((($vm1BeforeAssigned -gt 0) -and ($vm1BeforeDemand) -gt 0) -and (($vm2BeforeAssigned) -gt 0 -and ($vm2BeforeDemand -gt 0))) {
                break
            }
            $sleepPeriod-= 5
            Start-Sleep -S 5
        }
        if (($vm1BeforeAssigned -le 0) -or ($vm1BeforeDemand -le 0) -or ($vm2BeforeAssigned -le 0) -or ($vm2BeforeDemand -le 0))
        {
            throw "vm1 or vm2 reported 0 memory (assigned or demand)."
        }
        Write-LogInfo "Memory stats after both $vm1name and $vm2name started reporting"
        Write-LogInfo "$vm1name : assigned - $vm1BeforeAssigned | demand - $vm1BeforeDemand"
        Write-LogInfo "$vm2name : assigned - $vm2BeforeAssigned | demand - $vm2BeforeDemand"
        # Calculate the amount of memory to be consumed on VM2 with stress-ng
        [int64]$vm2ConsumeMem = (Get-VMMemory -VMName $vm1name -ComputerName $HvServer).Maximum
        # only consume 75% of max memory
        $vm2ConsumeMem = ($vm2ConsumeMem / 4) * 3
        # transform to MB
        $vm2ConsumeMem /= 1MB
        # standard chunks passed to stress-ng
        [int64]$chunks = 512 #MB
        [int]$vm2Duration = 420 #seconds
        # Send Command to consume
        $cmdAddConstants = "echo -e `"timeoutStress=$($timeoutStress)\nmemMB=$($vm2ConsumeMem)\nduration=$($vm2Duration)\nchunk=$($chunks)`" > /home/$user/constants.sh"
        Run-LinuxCmd -username $user -password $password -ip $VM1Ipv4 -port $VMPort -command $cmdAddConstants -runAsSudo
        $Memcheck = ". utils.sh && UtilsInit && ConsumeMemory"
        $job1 = Run-LinuxCmd -username $user -password $password -ip $VM1Ipv4 -port $VMPort -command $Memcheck -runAsSudo -RunInBackGround
        if (-not $?) {
            throw "Unable to start job for creating pressure on $vm1name" | Tee-Object -Append -file $summaryLog
        }
        # sleep a few seconds so all stresstestapp processes start and the memory assigned/demand gets updated
        Start-Sleep -S 200
        Write-LogInfo $job1.State
        # get memory stats for vm1 and vm2
        [int64[]]$vm2Assigned = @()
        [int64[]]$vm2Demand = @()
        [int64]$samples = 0
        # Wait for jobs to finish now and make sure they exited successfully
        $totalTimeout = $timeout = 1200
        $jobState = $false
        while ($timeout -gt 0)
        {
            if ($job1.State -like "Completed" -and -not $jobState) {
                $jobState = $true
                $retVal = Receive-Job $job1
                if (-not $retVal) {
                    Throw "Consume Memory script returned false on VM2 $vm2Name"
                }
                $diff = $totalTimeout - $timeout
                Write-LogInfo "Job1 finished in $diff seconds."
            }
            if ($jobState) {
                break
            }
            if (-not ($jobState)) {
                $vm2Assigned = $vm2Assigned + ($vm2.MemoryAssigned/1MB)
                $vm2Demand = $vm2Demand + ($vm2.MemoryDemand/1MB)
                $samples += 1
            }
            $timeout -= 1
            Start-Sleep -S 1
        }
        if (-not $jobState) {
            Throw "consume memory script did not finish in $totalTimeout seconds"
        }
        if ($samples -le 0) {
            Throw "No data has been sampled."
        }
        Write-LogInfo "Got $samples samples"
        # Get VM's Maximum memory setting
        [int64]$vm2MaxMem = ($vm1.MemoryMaximum/1MB)
        # $vm1bigger = $vm2bigger = 0
        # count the number of times vm1 had higher assigned memory
        for ($i = 0; $i -lt $samples; $i++) {
            if ($vm2Assigned[$i] -gt $vm2MaxMem) {
                Throw "$vm2Name assigned memory exceeded the maximum memory set"
            }
        }
        Stop-VM -VMName $vm2name -ComputerName $HvServer -force
        $testResult = $resultPass
    } catch {
        $ErrorMessage =  $_.Exception.Message
        $ErrorLine = $_.InvocationInfo.ScriptLineNumber
        Write-LogErr "$ErrorMessage at line: $ErrorLine"
    } finally {
        if (!$testResult) {
            $testResult = "ABORTED"
        }
        $resultArr += $testResult
    }
    $currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
    return $currentTestResult.TestResult
}
Main -VM1 $allVMData[0] -VM2 $allVMData[1] -TestParams (ConvertFrom-StringData $TestParams.Replace(";","`n"))
