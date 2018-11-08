# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
<#
.Synopsis
 Verify that demand changes with memory pressure inside the VM.

 Description:
   Verify that demand changes with memory pressure inside the VM.

   Only 1 VM is required for this test.

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

       "Tries=3;vmName=sles11x64sp3;enable=yes;minMem=512MB;maxMem=80%;startupMem=80%;memWeight=0;
       vmName=sles11x64sp3_2;enable=yes;minMem=512MB;maxMem=25%;startupMem=25%;memWeight=0"

   All scripts must return a boolean to indicate if the script completed successfully or not.

   .Parameter vmName
    Name of the VM to remove NIC from .

    .Parameter hvServer
    Name of the Hyper-V server hosting the VM.

    .Parameter testParams
    Test data for this test case
#>
param([string] $TestParams)
Set-PSDebug -Strict
#######################################################################
#
# Main script body
#
#######################################################################
function Main {
    param (
        $TestParams
    )
    $currentTestResult = CreateTestResultObject
    $resultArr = @()
    try {
        LogMsg "In DMpressure changes demand"
        $testResult = $null
        $captureVMData = $allVMData
        $VMName = $captureVMData.RoleName
        $HvServer= $captureVMData.HyperVhost
        $Ipv4 = $captureVMData.PublicIP
        $VMPort= $captureVMData.SSHPort
        if($null -eq $VMName){
            Throw ": VM name is null"
        }
        if($null -eq $HvServer){
            Throw "hvServer is null"
        }
        if($null -eq $TestParams){
            Throw ": testParams is null"
        }
        # Write out test Params
        #$TestParams
        # number of tries
        [int]$tries = 0
        # default number of tries
        Set-Variable defaultTries -option Constant -value 3
        Set-Location $WorkingDirectory
        if(-not $WorkingDirectory){
            throw "Mandatory param RootDir=Path; not found!"
        }
        $summaryLog = "${vmName}_summary.log"
        Remove-Item $summaryLog -ErrorAction SilentlyContinue
        if($tries -le 0){
            $tries = $defaultTries
        }
        $vm1 = Get-VM -Name $VMName -ComputerName $HvServer -ErrorAction SilentlyContinue
        $appGitURL = $TestParams.appGitURL
        $appGitTag = $TestParams.appGitTag
        # Install stress-ng if not installed
        LogMsg "Checking if stress-ng is installed"
        if($appGitURL){
            $retVal = Publish-App "stress-ng" $Ipv4 $appGitURL $appGitTag $VMPort
            if (-not $retVal){
                Throw "stress-ng is not installed! Please install it before running the memory stress tests." | Tee-Object -Append -file $summaryLog
            }
            LogMsg "stress-ng is installed! Will begin running memory stress tests shortly."
        }
        # get memory stats from vm1
        # wait up to 2 min for it
        $sleepPeriod = 120 #seconds
        # get VM1 Memory
        while ($sleepPeriod -gt 0)
        {
            [int64]$vm1BeforeAssigned = ($vm1.MemoryAssigned/1MB)
            [int64]$vm1BeforeDemand = ($vm1.MemoryDemand/1MB)
            if (($vm1BeforeAssigned -gt 0) -and ($vm1BeforeDemand -gt 0)){
                break
            }
            $sleepPeriod-= 5
            Start-Sleep -s 5
        }
        if (($vm1BeforeAssigned -le 0) -or ($vm1BeforeDemand -le 0)) {
            $testResult = $resultFail
            Throw "vm1 $vm1Name reported 0 memory (assigned or demand)." | Tee-Object -Append -file $summaryLog
        }
        $timeoutStress = 0
        $duration = 0
        $chunk = 0
        # Calculate the amount of memory to be consumed on VM1 and VM2 with stress-ng
        [int64]$vm1ConsumeMem = (Get-VMMemory -VMName $VMName -ComputerName $HvServer).Maximum
        # Transform to MB
        $vm1ConsumeMem /= 1MB
        LogMsg "Memory stats before start-ng started reporting "
        LogMsg "$vm1 assigned - $vm1BeforeAssigned | demand - $vm1BeforeDemand"
        # Send Command to consume
        $cmdAddConstants = "echo -e `"timeoutStress=$($timeoutStress)\nmemMB=$($vm1ConsumeMem)\nduration=$($duration)\nchunk=$($chunk)`" > /home/$user/constants.sh"
        RunLinuxCmd -username $user -password $password -ip $Ipv4 -port $VMPort -command $cmdAddConstants -runAsSudo
        $Memcheck = "echo '${password}' | sudo -S -s eval `"export HOME=``pwd``;. utils.sh && UtilsInit && ConsumeMemory`""
        $job1=RunLinuxCmd -username $user -password $password -ip $Ipv4 -port $VMPort -command $Memcheck -runAsSudo -RunInBackGround
        if (-not $?) {
            throw "Unable to start job for creating pressure on $VM1Name" | Tee-Object -Append -file $summaryLog
        }
        Start-Sleep -s 120
        # get memory stats for vm1 after stress-ng starts
        [int64]$vm1Assigned = ($vm1.MemoryAssigned/1MB)
        [int64]$vm1Demand = ($vm1.MemoryDemand/1MB)
        LogMsg "Memory stats after $vm1 started stress-ng"
        LogMsg "$vm1 assigned - $vm1Assigned | demand - $vm1Demand"
        if($vm1Demand -le $vm1BeforeDemand){
            $testResult = $resultFail
            Throw "Memory Demand did not increase after starting stress-ng" | Tee-Object -Append -file $summaryLog
        }
        # Wait for jobs to finish now and make sure they exited successfully
        $timeout = 120
        $firstJobStatus = $false
        while ($timeout -gt 0)
        {
            if($job1.Status -like "Completed"){
                $firstJobStatus = $true
                $retVal = Receive-Job $job1
                if (-not $retVal[-1]) {
                    Throw "Consume Memory script returned false on VM1 $VMName" | Tee-Object -Append -file $summaryLog
                }
            }
            if($firstJobStatus){
                break
            }
            $timeout -= 1
            Start-Sleep -s 1
        }
        # Verify if errors occured on guest
        $isAlive = Wait-ForVMToStartKVP  $VMName $HvServer 10
        if(-not $isAlive){
            $testResult = $resultFail
            Throw "VM is unresponsive after running the memory stress test" | Tee-Object -Append -file $summaryLog
        }
        # Everything ok
        LogMsg "Memory Demand changed with pressure on Linux guest" | Tee-Object -Append -file $summaryLog
        $testResult = $resultPass
    }
    catch {
        $ErrorMessage =  $_.Exception.Message
        $ErrorLine = $_.InvocationInfo.ScriptLineNumber
        LogErr "$ErrorMessage at line: $ErrorLine"
    }
    finally {
        if (!$testResult) {
            $testResult = "ABORTED"
        }
            $resultArr += $testResult
    }
    $currentTestResult.TestResult = GetFinalResultHeader -resultarr $resultArr
    return $currentTestResult.TestResult
}

Main -TestParams (ConvertFrom-StringData $TestParams.Replace(";","`n"))
