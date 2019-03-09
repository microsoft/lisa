# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
<#
.Synopsis
 Verify that high priority VMs are preferentially served memory.

 Description:
   Verify that VMs with high memory priority get assigned more memory under pressure, than a VM with lower priority.

   2 VMs are required for this test.

   The testParams have the format of:

       enableDM=[yes|no], minMem= (decimal) [MB|GB|%], maxMem=(decimal) [MB|GB|%],
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
       "Tries=3;VM1Name=ICA-HG*-role-0;enableDM1=yes;minMem1=512MB;maxMem1=80%;startupMem1=80%;memWeight1=0;
       VM2Name=ICA-HG*-role-1;enableDM2=yes;minMem2=512MB;maxMem2=25%;startupMem2=25%;memWeight2=0"

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
        $VM1Name = $VM1.RoleName
        $VM2Name = $VM2.RoleName
        $HvServer= $VM1.HyperVhost
        $VMPort= $VM1.SSHPort
        # Check input arguments
        if ($null -eq $VM1Name) {
            throw "VM name is null"
        }
        if ($null-eq $VM2Name) {
            throw "VM name is null"
        }
        if ($null -eq $HvServer) {
            throw "hvServer is null"
        }
        # change working directory to root dir
        Set-Location $WorkingDirectory
        if (-not $WorkingDirectory) {
            throw "Mandatory param RootDir=Path; not found!"
        }
        $appGitURL=$TestParams.appGitURL
        $appGitTag=$TestParams.appGitTag
        $memweight1=$TestParams.memWeight1
        $memweight2=$TestParams.memWeight2
        Set-VMDynamicMemory -VM $VM1 -minMem $TestParams.minMem1 -maxMem $TestParams.maxMem1 `
            -startupMem $TestParams.startupMem1 -memWeight $memweight1  | Out-Null
        Set-VMDynamicMemory -VM $VM2 -minMem $TestParams.minMem2 -maxMem $TestParams.maxMem2 `
            -startupMem $TestParams.startupMem2 -memWeight $memweight2 | Out-Null
        # Waiting for the VM to run again and respond to SSH - port 22
        $VM1Ipv4 = Start-VMandGetIP $VM1Name $HvServer $VMPort $user $password
        $summaryLog = "${vmName}_summary.log"
        Remove-Item $summaryLog -ErrorAction SilentlyContinue
        $vm2 = Get-VM -Name $VM2Name -ComputerName $HvServer -ErrorAction SilentlyContinue
        $vm1 = Get-VM -Name $VM1Name -ComputerName $HvServer -ErrorAction SilentlyContinue
        #Install stress-ng if not installed
        Write-LogInfo "Checking if stress-ng is installed"
        $retVal = Publish-App "stress-ng" $VM1Ipv4 $appGitURL $appGitTag $VMPort
        if (-not $retVal) {
            throw "stress-ng is not installed! Please install it before running the memory stress tests."
        }
        Write-LogInfo "stress-ng is installed on $VM1Name. Will begin running memory stress tests shortly."
        #
        # LIS Started VM1, so start VM2
        #
        $vm2Ipv4 = Start-VMandGetIP $VM2Name $HvServer $VMPort $user $password
        $timeoutStress = 0
        $sleepPeriod = 120 #seconds
        # get VM1 and VM2's Memory
        while ($sleepPeriod -gt 0) {
            [int64]$vm1BeforeAssigned = ($vm1.MemoryAssigned/1MB)
            [int64]$vm1BeforeDemand = ($vm1.MemoryDemand/1MB)
            [int64]$vm2BeforeAssigned = ($vm2.MemoryAssigned/1MB)
            [int64]$vm2BeforeDemand = ($vm2.MemoryDemand/1MB)
            if (($vm1BeforeAssigned -gt 0) -and ($vm1BeforeDemand -gt 0) -and ($vm2BeforeAssigned -gt 0) -and ($vm2BeforeDemand -gt 0)) {
                break
            }
            $sleepPeriod-= 5
            Start-Sleep -s 5
        }
        if (($vm1BeforeAssigned -le 0) -or ($vm1BeforeDemand -le 0) -or ($vm2BeforeAssigned -le 0) -or ($vm2BeforeDemand -le 0)) {
            throw "vm1 or vm2 reported 0 memory (assigned or demand)."
        }
        Write-LogInfo "Memory stats after both $VM1Name and $VM2Name started reporting"
        Write-LogInfo "${VM1Name}: assigned - $vm1BeforeAssigned | demand - $vm1BeforeDemand"
        Write-LogInfo "${VM2Name}: assigned - $vm2BeforeAssigned | demand - $vm2BeforeDemand"
        # Install stress-ng if not installed
        Write-LogInfo "Checking if stress-ng is installed on other VM"
        $retVal = Publish-App "stress-ng" $vm2ipv4 $appGitURL $appGitTag $VMPort
        if (-not $retVal) {
            throw "stress-ng is not installed on $VM2Name! Please install it before running the memory stress tests."
        }
        Write-LogInfo "stress-ng is installed on $VM2Name! Will begin running memory stress tests shortly."
        $timeoutStress=0
        # Calculate the amount of memory to be consumed on VM1 and VM2 with stress-ng
        [int64]$vm1ConsumeMem = (Get-VMMemory -VMName $VM1Name -ComputerName $HvServer).Maximum
        [int64]$vm2ConsumeMem = (Get-VMMemory -VMName $VM2Name -ComputerName $HvServer).Maximum
        # only consume 75% of max memory
        $vm1ConsumeMem = ($vm1ConsumeMem / 4) * 3
        $vm2ConsumeMem = ($vm2ConsumeMem / 4) * 3
        # transform to MB
        $vm1ConsumeMem /= 1MB
        $vm2ConsumeMem /= 1MB
        # standard chunks passed to stress-ng
        [int64]$chunks = 512 #MB
        [int]$vm1Duration = 400 #seconds
        [int]$vm2Duration = 380 #seconds
        # Send Command to consume
        $cmdAddConstants = "echo -e `"timeoutStress=$($timeoutStress)\nmemMB=$($vm1ConsumeMem)\nduration=$($vm1Duration)\nchunk=$($chunks)`" > /home/$user/constants.sh"
        $null = Run-LinuxCmd -username $user -password $password -ip $VM1Ipv4 -port $VMPort -command $cmdAddConstants -runAsSudo
        $Memcheck = ". utils.sh && UtilsInit && ConsumeMemory"
        $job1 = Run-LinuxCmd -username $user -password $password -ip $VM1Ipv4 -port $VMPort -command $Memcheck -runAsSudo -RunInBackGround
        if (-not $?) {
            throw "Unable to start job for creating pressure on $VM1Name"
        }
        $cmdAddConstants = "echo -e `"timeoutStress=$($timeoutStress)\nmemMB=$($vm2ConsumeMem)\nduration=$($vm2Duration)\nchunk=$($chunks)`" > /home/$user/constants.sh"
        $null = Run-LinuxCmd -username $user -password $password -ip $vm2Ipv4 -port $VMPort -command $cmdAddConstants -runAsSudo
        $job2 = Run-LinuxCmd -username $user -password $password -ip $vm2Ipv4 -port $VMPort -command $Memcheck -runAsSudo -RunInBackGround
        if (-not $?) {
            throw "Unable to start job for creating pressure on $VM2Name"
        }
        # sleep a few seconds so all stress-ng processes start and the memory assigned/demand gets updated
        Start-Sleep -S 200
        # get memory stats for vm1 and vm2
        [int64[]]$vm1Assigned = @()
        [int64[]]$vm1Demand = @()
        [int64[]]$vm2Assigned = @()
        [int64[]]$vm2Demand = @()
        [int64]$samples = 0
        # Wait for jobs to finish now and make sure they exited successfully
        $totalTimeout = $timeout = 420
        $firstJobState = $false
        $secondJobState = $false
        while ($timeout -gt 0) {
            if ($job1.State -like "Completed" -and -not $firstJobState) {
                $firstJobState = $true
                $retVal = Receive-Job $job1
                if (-not $retVal) {
                    throw "Consume Memory script returned false on VM1 $VM1Name"
                }
                $diff = $totalTimeout - $timeout
                Write-LogInfo "Job1 finished in $diff seconds."
            }
            if ($job2.State -like "Completed" -and -not $secondJobState) {
                $secondJobState = $true
                $retVal = Receive-Job $job2
                if (-not $retVal) {
                    throw "Consume Memory script returned false on VM2 $VM2Name"
                }
                $diff = $totalTimeout - $timeout
                Write-LogInfo "Job2 finished in $diff seconds."
            }
            if ($firstJobState -and $secondJobState) {
                break
            }
            if (-not ($firstJobState -or $secondJobState)) {
                $vm1Assigned = $vm1Assigned + ($vm1.MemoryAssigned/1MB)
                $vm2Assigned = $vm2Assigned + ($vm2.MemoryAssigned/1MB)
                $vm1Demand = $vm1Demand + ($vm1.MemoryDemand/1MB)
                $vm2Demand = $vm2Demand + ($vm2.MemoryDemand/1MB)
                $samples += 1
            }
            if ($timeout -le 0) {
                break
            }
            $timeout -= 1
            Start-Sleep -s 1
        }
        if ($samples -le 0) {
            throw "No data has been sampled."
        }
        Write-LogInfo "Got $samples samples"
        $vm1bigger = $vm2bigger = 0
        # count the number of times vm1 had higher assigned memory
        for ($i = 0; $i -lt $samples; $i++) {
            if ($vm1Assigned[$i] -gt $vm2Assigned[$i]) {
                $vm1bigger += 1
            }
            else {
                $vm2bigger += 1
            }
            Write-LogInfo "sample ${i}: vm1 = $vm1Assigned[$i] - vm2 = $vm2Assigned[$i]"
        }
        if ($vm1bigger -le $vm2bigger) {
            throw "$VM1Name didn't grow faster than $VM2Name"
        }
        # stop vm2
        Stop-VM -VMName $VM2Name -ComputerName $HvServer -force
        # Verify if errors occured on VM1
        $timeout=10
        $isAlive = Wait-ForVMToStartKVP $VM1Name $HvServer $timeout
        if (-not $isAlive) {
            throw "VM is unresponsive after running the memory stress test"
        }
        # Everything ok
        Write-LogInfo "Success High priority VM received more memory under same pressure"
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
