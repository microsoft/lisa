# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
 <#
.Synopsis
    Verify that a VM with low memory pressure looses memory when another
    VM has a high memory demand. 3 VMs are required for this test.
    The testParams have the format of:
	vmName=Name of a VM, enable=[yes|no], minMem= (decimal) [MB|GB|%],
	maxMem=(decimal) [MB|GB|%], startupMem=(decimal) [MB|GB|%],
	memWeight=(0 < decimal < 100)
 	Tries=(decimal): This controls the number of times the script tries
	to start the second VM. If not set, a default value of 3 is set. This
	is necessary because Hyper-V usually removes memory from a VM only when
	a second one applies pressure. However, the second VM can fail to start
	while memory is removed from the first. There is a 30 second timeout
	between tries, so 3 tries is a conservative value.
 	Example of testParam to configure Dynamic Memory:
	"Tries=3;vmName=sles11x64sp3;enable=yes;minMem=512MB;maxMem=80%;
	startupMem=80%;memWeight=0;vmName=sles11x64sp3_2;enable=yes;
	minMem=512MB;maxMem=25%;startupMem=25%;memWeight=0"
 .Parameter testParams
	Test data for this test case
#>
param([String] $TestParams,
      [object] $AllVmData)
Function Main
{
    param (
        $VM1,
        $VM2,
        $VM3,
        $TestParams
    )
    $currentTestResult = Create-TestResultObject
	try{
        $testResult = $null
        $memweight1=$TestParams.memWeight1
        $memweight2=$TestParams.memWeight2
        $memweight3=$TestParams.memWeight3
        $VM1Name=$VM1.RoleName
        $VM2Name=$VM2.RoleName
        $VM3Name=$VM3.RoleName
        $VM1Ipv4=$VM1.PublicIP
        $HvServer=$VM1.HyperVHost
        $VMPort=$VM2.SSHPort
        $appGitURL = $TestParams.appGitURL
        $appGitTag = $TestParams.appGitTag
        # Change working directory to root dir
        Set-Location $WorkingDirectory
        Set-VMDynamicMemory -VM $VM1 -minMem $TestParams.minMem1 -maxMem $TestParams.maxMem1 `
            -startupMem $TestParams.startupMem1 -memWeight $memweight1 | Out-Null
        Set-VMDynamicMemory -VM $VM2 -minMem $TestParams.minMem2 -maxMem $TestParams.maxMem2 `
            -startupMem $TestParams.startupMem2 -memWeight $memweight2 | Out-Null
        Set-VMDynamicMemory -VM $VM3 -minMem $TestParams.minMem3 -maxMem $TestParams.maxMem3 `
            -startupMem $TestParams.startupMem3 -memWeight $memweight3 | Out-Null
        Write-LogInfo "Starting VM1 $VM1Name"
        $VM1Ipv4=Start-VMandGetIP $VM1Name $HvServer $VMPort $user $password
        $vm1 = Get-VM -Name $VM1Name -ComputerName $HvServer -ErrorAction SilentlyContinue
        $vm2 = Get-VM -Name $VM2Name -ComputerName $HvServer -ErrorAction SilentlyContinue
        $vm3 = Get-VM -Name $VM3Name -ComputerName $HvServer -ErrorAction SilentlyContinue
        # determine which is vm2 and which is vm3 based on memory weight
        $vm2MemWeight = (Get-VMMemory -VMName $VM2Name -ComputerName $HvServer).Priority
        if (-not $?) {
            throw "Unable to get $VM2Name memory weight."
        }
 	    $vm3MemWeight = (Get-VMMemory -VMName $VM3Name -ComputerName $HvServer).Priority
	    if (-not $?) {
		    throw "Unable to get $VM3Name memory weight."
        }
        if ($vm3MemWeight -eq $vm2MemWeight) {
	    throw "$VM3Name must have a higher memory weight than $VM2Name"
        }
        if ($vm3MemWeight -lt $vm2MemWeight) {
	        # switch vm2 with vm3
	        $aux = $VM2Name
	        $VM2Name = $VM3Name
	        $VM3Name = $aux
	        $vm2 = Get-VM -Name $VM2Name -ComputerName $HvServer -ErrorAction SilentlyContinue
	        if (-not $vm2) {
		        throw "VM $VM2Name does not exist anymore"
	        }
	        $vm3 = Get-VM -Name $VM3Name -ComputerName $HvServer -ErrorAction SilentlyContinue
	        if (-not $vm3) {
		        throw "VM $VM3Name does not exist anymore"
	        }
        }
        # Check if stress-ng is installed
        Write-LogInfo "Checking if stress-ng is installed"
        $retVal1 = Publish-App "stress-ng" $VM1Ipv4 $appGitURL $appGitTag $VMPort
        if (-not $retVal1) {
            throw "stress-ng is not installed for VM1! Please install it before running the memory stress tests."
        }
        Write-LogInfo "stress-ng is installed on $VM1Name ! Will begin running memory stress tests shortly."
        # LIS Started VM1, so start VM2
        $VM2Ipv4 = Start-VMandGetIP $VM2Name $HvServer $VMPort $user $password
        $timeoutStress = 1
        $sleepPeriod = 120 #seconds
        # get VM1 and VM2's Memory
        while ($sleepPeriod -gt 0) {
            [int64]$vm1BeforeAssigned = ($vm1.MemoryAssigned/[int64]1048576)
	        [int64]$vm1BeforeDemand = ($vm1.MemoryDemand/[int64]1048576)
	        [int64]$vm2BeforeAssigned = ($vm2.MemoryAssigned/[int64]1048576)
	        [int64]$vm2BeforeDemand = ($vm2.MemoryDemand/[int64]1048576)
            if ($vm1BeforeAssigned -gt 0 -and $vm1BeforeDemand -gt 0 -and $vm2BeforeAssigned -gt 0 -and $vm2BeforeDemand -gt 0) {
                break
	        }
            $sleepPeriod-= 5
            Start-Sleep -s 5
        }
        Write-LogInfo "Memory stats after both $VM1Name and $VM2Name started reporting:"
        Write-LogInfo "$VM1Name : assigned - $vm1BeforeAssigned | demand - $vm1BeforeDemand"
        Write-LogInfo "$VM2Name : assigned - $vm2BeforeAssigned | demand - $vm2BeforeDemand"
        if ($vm1BeforeAssigned -le 0 -or $vm1BeforeDemand -le 0) {
	        throw "VM1 $VM1Name or VM2 $VM2Name reported 0 memory (assigned or demand)."
        }
        # Check if stress-ng is installed for vm2
        Write-LogInfo "Checking if stress-ng is installed"
        $retVal2 = Publish-App "stress-ng" $VM2Ipv4 $appGitURL $appGitTag $VMPort
        if (-not $retVal2) {
            throw "stress-ng is not installed for VM2! Please install it before running the memory stress tests."
        }
        Write-LogInfo "stress-ng is installed on $VM2Name ! Will begin running memory stress tests shortly."
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
        $cmdAddConstants = "echo -e `"timeoutStress=$($timeoutStress)\nmemMB=$($vm1ConsumeMem)\nduration=$($vm1Duration)\nchunk=$($chunks)`" > /home/$user/constants.sh"
        Run-LinuxCmd -username $user -password $password -ip $VM1Ipv4 -port $VMPort -command $cmdAddConstants -runAsSudo
        $Memcheck = "echo '${password}' | sudo -S -s eval `"export HOME=``pwd``;. utils.sh && UtilsInit && ConsumeMemory`""
        $job1 = Run-LinuxCmd -username $user -password $password -ip $VM1Ipv4 -port $VMPort -command $Memcheck -runAsSudo -RunInBackGround
        if (-not $job1) {
            throw "Unable to start job for creating pressure on $VM1Name" | Tee-Object -Append -file $summaryLog
        }
        $cmdAddConstants = "echo -e `"timeoutStress=$($timeoutStress)\nmemMB=$($vm2ConsumeMem)\nduration=$($vm2Duration)\nchunk=$($chunks)`" > /home/$user/constants.sh"
        Run-LinuxCmd -username $user -password $password -ip $vm2Ipv4 -port $VMPort -command $cmdAddConstants -runAsSudo
        $job2 = Run-LinuxCmd -username $user -password $password -ip $vm2Ipv4 -port $VMPort -command $Memcheck -runAsSudo -RunInBackGround
        if (-not $job2) {
            throw "Unable to start job for creating pressure on $VM2Name" | Tee-Object -Append -file $summaryLog
        }
        # sleep a few seconds so all stress-ng processes start and the memory assigned/demand gets updated
        Start-Sleep -s 240
        # get memory stats for vm1 and vm2 just before vm3 starts
        [int64]$vm1Assigned = ($vm1.MemoryAssigned/[int64]1048576)
        [int64]$vm1Demand = ($vm1.MemoryDemand/[int64]1048576)
        [int64]$vm2Assigned = ($vm2.MemoryAssigned/[int64]1048576)
        [int64]$vm2Demand = ($vm2.MemoryDemand/[int64]1048576)
        Write-LogInfo "Memory stats after $VM1Name and $VM2Name started stress-ng, but before $VM3Name starts: "
        Write-LogInfo "$VM1Name : assigned - $vm1Assigned | demand - $vm1Demand"
        Write-LogInfo "$VM2Name : assigned - $vm2Assigned | demand - $vm2Demand"
        # Try to start VM3
        $VM3Ipv4=Start-VMandGetIP $VM3Name $HvServer $VMPort $user $password
        Write-LogInfo "IP of $VM3Name is $VM3Ipv4"
        # get memory stats after vm3 started
        [int64]$vm1AfterAssigned = ($vm1.MemoryAssigned/[int64]1048576)
        [int64]$vm1AfterDemand = ($vm1.MemoryDemand/[int64]1048576)
        [int64]$vm2AfterAssigned = ($vm2.MemoryAssigned/[int64]1048576)
        [int64]$vm2AfterDemand = ($vm2.MemoryDemand/[int64]1048576)
        Write-LogInfo "Memory stats after $VM1Name and $VM2Name started stress-ng and after $VM3Name started: "
        Write-LogInfo "$VM1Name : assigned - $vm1AfterAssigned | demand - $vm1AfterDemand"
        Write-LogInfo "$VM2Name : assigned - $vm2AfterAssigned | demand - $vm2AfterDemand"
        # Wait for jobs to finish now and make sure they exited successfully
        $totalTimeout = $timeout = 120
        $timeout = 0
        $firstJobState = $false
        $secondJobState = $false
        $min=0
        while ($true) {
            if ($job1.State -like "Completed" -and -not $firstJobState) {
                $firstJobState = $true
                $retVal = Receive-Job $job1
                if (-not $retVal) {
                    throw "Consume Memory script returned false on VM1 $VM1Name"
                }
                $diff = $totalTimeout - $timeout
                Write-LogInfo "Job1 finished in $diff minutes."
            }
            if ($job2.State -like "Completed" -and -not $secondJobState) {
                $secondJobState = $true
                $retVal = Receive-Job $job2
                if (-not $retVal) {
                    throw "Consume Memory script returned false on VM2 $VM2Name"
                }
                $diff = $totalTimeout - $timeout
                Write-LogInfo "Job2 finished in $diff minutes."
            }
            if ($firstJobState -and $secondJobState) {
                break
            }
            if ($timeout%60 -eq 0) {
                Write-LogInfo "$min minutes passed"
                $min += 1
            }
            if ($totalTimeout -le 0) {
                break
	        }
            $timeout += 5
            $totalTimeout -= 5
            Start-Sleep -s 5
        }
        [int64]$vm1DeltaAssigned = [int64]$vm1Assigned - [int64]$vm1AfterAssigned
        [int64]$vm1DeltaDemand = [int64]$vm1Demand - [int64]$vm1AfterDemand
        [int64]$vm2DeltaAssigned = [int64]$vm2Assigned - [int64]$vm2AfterAssigned
        [int64]$vm2DeltaDemand = [int64]$vm2Demand - [int64]$vm2AfterDemand
        Write-LogInfo "Deltas for $VM1Name and $VM2Name after $VM3Name started"
        Write-LogInfo "$VM1Name : deltaAssigned - $vm1DeltaAssigned | deltaDemand - $vm1DeltaDemand"
        Write-LogInfo "$VM2Name : deltaAssigned - $vm2DeltaAssigned | deltaDemand - $vm2DeltaDemand"
        # check that at least one of the first two VMs has lower assigned memory as a result of VM3 starting
        if ($vm1DeltaAssigned -le 0 -and $vm2DeltaAssigned -le 0) {
	        throw "Neither $VM1Name, nor $VM2Name didn't lower their assigned memory in response to $VM3Name starting"
	    }
        [int64]$vm1EndAssigned = ($vm1.MemoryAssigned/[int64]1048576)
        [int64]$vm1EndDemand = ($vm1.MemoryDemand/[int64]1048576)
        [int64]$vm2EndAssigned = ($vm2.MemoryAssigned/[int64]1048576)
        [int64]$vm2EndDemand = ($vm2.MemoryDemand/[int64]1048576)
        $sleepPeriod = 120 #seconds
        # get VM3's Memory
        while ($sleepPeriod -gt 0) {
            [int64]$vm3EndAssigned = ($vm3.MemoryAssigned/[int64]1048576)
            [int64]$vm3EndDemand = ($vm3.MemoryDemand/[int64]1048576)
            if ($vm3EndAssigned -gt 0 -and $vm3EndDemand -gt 0) {
                    break
	        }
            $sleepPeriod -= 5
            Start-Sleep -s 5
        }
        if ($vm1EndAssigned -le 0 -or $vm1EndDemand -le 0 -or $vm2EndAssigned -le 0 -or $vm2EndDemand -le 0 -or $vm3EndAssigned -le 0 -or $vm3EndDemand -le 0) {
	        throw "One of the VMs reports 0 memory (assigned or demand) after VM3 $VM3Name started"
        }
        $isAlive = Wait-ForVMToStartKVP $VM1Name $HvServer 10
        if (-not $isAlive) {
            Write-LogErr "VM is unresponsive after running the memory stress test"
            $testResult = $resultFail
        } else {
            # Everything ok
            Write-LogInfo "Success: Memory was removed from a low priority VM with minimal memory pressure to a VM with high memory pressure!"
            $testResult = $resultPass
        }
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
Main -VM1 $allVMData[0] -VM2 $allVMData[1] -VM3 $allVMData[2] -TestParams (ConvertFrom-StringData $TestParams.Replace(";","`n"))
