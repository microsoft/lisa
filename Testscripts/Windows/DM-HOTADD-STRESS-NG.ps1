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
        $TestParams, $AllVmData
    )
    $currentTestResult = Create-TestResultObject
    $resultArr = @()
    try {
        $testResult = $null
        $captureVMData = $allVMData
        $VMName = $captureVMData.RoleName
        $HvServer= $captureVMData.HyperVhost
        $Ipv4 = $captureVMData.PublicIP
        $VMPort= $captureVMData.SSHPort
        # Check input arguments
        if (-not $VMName) {
            throw "VM name is null. "
        }
        Write-LogInfo "VMName $VMName"
        if (-not $HvServer) {
            throw "hvServer name is null. "
        }
        if (-not $TestParams) {
            throw "TestParams is null. "
        }
        # Write out test Params
        Write-LogInfo "Test Param $TestParams"
        # Name of first VM
        $VM1Name = $VMName
        # Number of tries
        # Default number of tries
        Set-Variable defaultTries -option Constant -value 3
        # Change working directory to root dir
        Set-Location $WorkingDirectory
        if (-not $WorkingDirectory) {
            throw "INFO : Mandatory param RootDir=Path; not found!"
        }
        $timeoutStress = $TestParams.Stress_Level
        $appGitURL = $TestParams.appGitURL
        $appGitTag = $TestParams.appGitTag
        #Write-LogInfo "Tries $tries"
        Write-LogInfo "appGitURL $appGitURL"
        Write-LogInfo "Git tag is $appGitTag"
        $summaryLog = "${vmName}_summary.log"
        Remove-Item $summaryLog -ErrorAction SilentlyContinue
        $vmInfo = Get-VM -Name $vm1Name -ComputerName $hvServer -ErrorAction SilentlyContinue
        if (-not $vmInfo) {
            throw "VM $vm1Name does not exist"
        }
        # Install stress-ng if not installed
        if($appGitURL) {
            Write-LogInfo "Stress-ng installation started"
            $retVal = Publish-App "stress-ng" $Ipv4 $appGitURL $appGitTag $VMPort
            if (-not $retVal)
            {
                Throw "stress-ng could not be installed! Please install it before running the memory stress tests." | Tee-Object -Append -file $summaryLog
            }
            Write-LogInfo "Stress-ng is installed"
        }
        Start-Sleep -Seconds 40
        $sleepPeriod = 120 #seconds
        # Get VM1 Memory
        while ($sleepPeriod -gt 0)
        {
            [int64]$vm1BeforeAssigned = ($vmInfo.MemoryAssigned/1MB)
            [int64]$vm1BeforeDemand = ($vmInfo.MemoryDemand/1MB)
            if ($vm1BeforeAssigned -gt 0 -and $vm1BeforeDemand -gt 0) {
                break
            }
            $sleepPeriod-= 5
            Start-Sleep -Seconds 5
        }
        if (($vm1BeforeAssigned -le 0) -or ($vm1BeforeDemand -le 0)) {
            $testResult = $resultFail
            Throw "vm1 $vm1Name reported 0 memory (assigned or demand)." | Tee-Object -Append -file $summaryLog
        }
        Write-LogInfo "Memory stats after $vm1Name started reporting"
        Write-LogInfo "${vm1Name}: assigned - $vm1BeforeAssigned | demand - $vm1BeforeDemand"
        # Set the amount of sleep time needed
        if ($timeoutStress -eq 0) {
            $sleepTime = 20
            $duration = 0
            $chunk = 0
        }
        elseif ($timeoutStress -eq 1) {
            $sleepTime = 60
            $duration = 120
            $chunk = 1
        }
        elseif ($timeoutStress -eq 2) {
            $sleepTime = 20
            $duration = 40
            $chunk = 1
        }
        else {
          $sleepTime = 20
          $duration = 40
          $chunk = 1
        }
        # Calculate the amount of memory to be consumed on VM1 and VM2 with stress-ng
        [int64]$vm1ConsumeMem = (Get-VMMemory -VM $vmInfo).Maximum
        # Transform to MB
        $vm1ConsumeMem /= 1MB
        # Send Command to consume
        if ($timeoutStress -ge 1) {
            $startMemory = Get-MemoryStressNG $Ipv4 $VMPort $timeoutStress $vm1ConsumeMem $duration $chunk
        }
        else {
            $startMemory = Start-StressNg $Ipv4 $VMPort
        }
        if (-not $startMemory){
           Throw "Unable to start job for creating pressure on $vm1Name" | Tee-Object -Append -file $summaryLog
        }
        # Wait for stress-ng to start and the memory assigned/demand gets updated
        Start-Sleep -Seconds $sleepTime
        [int64]$vm1Demand = ($vmInfo.MemoryDemand/1MB)
        # Get memory stats for vm1 after stress-ng starts
        [int64]$vm1Assigned = ($vmInfo.MemoryAssigned/1MB)
        Write-LogInfo "Memory stats for $vm1Name after stress-ng started"
        Write-LogInfo "${vm1Name}: assigned - $vm1Assigned | demand - $vm1Demand"
        Write-LogInfo "vm1BeforeDemand $vm1BeforeDemand vm1Demand  $vm1Demand"
        if ($vm1Demand -le $vm1BeforeDemand) {
            $testResult = $resultFail
            Throw "Memory Demand did not increase after starting stress-ng" | Tee-Object -Append -file $summaryLog
        }
        # Wait for jobs to finish now and make sure they exited successfully
        $timeout = 240
        while ($timeout -gt 0)
        {
            $timeout -= 5
            Start-Sleep -Seconds 5
        }
        # Verify if errors occured on guest
        $isAlive = Wait-ForVMToStartKVP $vm1Name $hvServer 10
        if (-not $isAlive){
            $testResult = $resultFail
            Throw "VM is unresponsive after running the memory stress test" | Tee-Object -Append -file $summaryLog
        }
        Start-Sleep -Seconds 20
        # Get memory stats after stress-ng finished
        [int64]$vm1AfterAssigned = ($vmInfo.MemoryAssigned/1MB)
        [int64]$vm1AfterDemand = ($vmInfo.MemoryDemand/1MB)
        Write-LogInfo "Memory stats after stress-ng finished: "
        Write-LogInfo "  ${vm1Name}: assigned - $vm1AfterAssigned | demand - $vm1AfterDemand"
        Write-LogInfo "vm1AfterDemand $vm1AfterDemand vm1Demand $vm1Demand"
        if ($vm1AfterDemand -ge $vm1Demand) {
            $testResult = $resultFail
            Throw "Demand did not go down after stress-ng finished." | Tee-Object -Append -file $summaryLog
        }
        Write-LogInfo "Memory Hot Add (using stress-ng) completed successfully!" | Tee-Object -Append -file $summaryLog
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

Main -TestParams (ConvertFrom-StringData $TestParams.Replace(";","`n")) -AllVmData $AllVmData
