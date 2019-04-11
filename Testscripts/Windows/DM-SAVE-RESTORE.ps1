# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
<#
.Synopsis
 Perform Save/Start operations on VMs with Dynamic Memory enabled.

 Description:
  Perform Save/Start operations on VMs with Dynamic Memory enabled and make sure VMs remain stable.

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
    try {
        $resultArr = @()
        $testResult = $null
        $VM1Name = $VM1.RoleName
        $VM2Name = $VM2.RoleName
        $HvServer= $VM1.HyperVhost
        $VMPort=$VM1.SSHPort
        # Check input arguments
        if ($null -eq $VM1Name) {
            throw "VM name is null"
        }
        if ($null-eq $VM2Name ) {
            throw "VM name is null"
        }
        if ($null -eq $HvServer) {
            throw "hvServer is null"
        }
        $memWeight1=$TestParams.memweight1
        $memWeight2=$TestParams.memweight2
        Set-VMDynamicMemory -VM $VM1 -minMem $TestParams.minMem1 -maxMem $TestParams.maxMem1 `
            -startupMem $TestParams.startupMem1 -memWeight $memweight1 | Out-Null
        Set-VMDynamicMemory -VM $VM2 -minMem $TestParams.minMem2 -maxMem $TestParams.maxMem2 `
            -startupMem $TestParams.startupMem2 -memWeight $memweight2 | Out-Null
        $VM1Ipv4=Start-VMandGetIP $VM1Name $HvServer $VMPort $user $password
        Write-LogInfo "IP of $VM1Name is $VM1Ipv4"
        # change working directory to root dir
        Set-Location $WorkingDirectory
        if (-not $WorkingDirectory) {
            throw "Mandatory param RootDir=Path; not found!"
        }
        $summaryLog = "${vmName}_summary.log"
        Remove-Item $summaryLog -ErrorAction SilentlyContinue
        $vm1 = Get-VM -Name $VM1Name -ComputerName $HvServer -ErrorAction SilentlyContinue
        $vm2 = Get-VM -Name $VM2Name -ComputerName $HvServer -ErrorAction SilentlyContinue
        # sleep 1 minute for VM to start reporting demand
        $sleepPeriod = 60
        while ($sleepPeriod -gt 0) {
            # get VM1's Memory
            [int64]$vm1BeforeAssigned = ($vm1.MemoryAssigned/[int64]1048576)
            [int64]$vm1BeforeDemand = ($vm1.MemoryDemand/[int64]1048576)
            if (($vm1BeforeAssigned -gt 0) -and ($vm1BeforeDemand -gt 0)) {
                break
            }
            $sleepPeriod -= 5
            Start-Sleep -s 5
        }
        if ($vm1BeforeAssigned -le 0) {
            $testResult = $resultFail
            throw "$VM1Name Assigned memory is 0" | Tee-Object -Append -file $summaryLog
        }
        if ($vm1BeforeDemand -le 0) {
            $testResult = $resultFail
            throw "$VM1Name Memory demand is 0" | Tee-Object -Append -file $summaryLog
        }
        Write-LogInfo "VM1 $VM1Name before assigned memory : $vm1BeforeAssigned"
        Write-LogInfo "VM1 $VM1Name before memory demand: $vm1BeforeDemand"
        #
        # LIS Started VM1, so start VM2
        #
        $VM2Ipv4 = Start-VMandGetIP $VM2Name $HvServer $VMPort $user $password
        Write-LogInfo "IP of $VM2Name is $VM2Ipv4"
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
        if ($vm2BeforeAssigned -le 0) {
            $testResult = $resultFail
            throw "$VM2Name Assigned memory is 0" | Tee-Object -Append -file $summaryLog
        }
        if ($vm2BeforeDemand -le 0) {
            $testResult = $resultFail
            throw "$VM2Name Memory demand is 0" | Tee-Object -Append -file $summaryLog
        }
        Write-LogInfo "VM2 $VM2Name before assigned memory : $vm2BeforeAssigned"
        Write-LogInfo "VM2 $VM2Name before memory demand: $vm2BeforeDemand"
        # Save VM2
        Save-VM $VM2Name -ComputerName $HvServer -ErrorAction SilentlyContinue
        if (-not $?) {
            throw "Unable to save vm2 $VM2Name on $HvServer" | Tee-Object -Append -file $summaryLog
        }
        Start-VM -Name $VM2Name -ComputerName $HvServer -ErrorAction SilentlyContinue
        if (-not $?) {
            throw "Unable to start VM2 $VM2Name after saving it" | Tee-Object -Append -file $summaryLog
        }
        Start-Sleep -s 60
        # get VM2's Memory
        [int64]$vm2AfterAssigned = ($vm2.MemoryAssigned/[int64]1048576)
        [int64]$vm2AfterDemand = ($vm2.MemoryDemand/[int64]1048576)
        if ($vm2AfterAssigned -le 0) {
            $testResult = $resultFail
            throw "$VM2Name Assigned memory is 0 after it started from save" | Tee-Object -Append -file $summaryLog
        }
        if ($vm2AfterDemand -le 0) {
            $testResult = $resultFail
            throw "$VM2Name Memory demand is $vm2AfterDemand after it started from save." | Tee-Object -Append -file $summaryLog
        }
        Write-LogInfo "VM2 $VM2Name after assigned memory : $vm2AfterAssigned"
        Write-LogInfo "VM2 $VM2Name after memory demand: $vm2AfterDemand"
        # Save VM1
        Save-VM $VM1Name -ComputerName $HvServer -ErrorAction SilentlyContinue
        if (-not $?) {
            throw "Unable to save VM1 $VM1Name" | Tee-Object -Append -file $summaryLog
        }
        Start-VM -Name $VM1Name -ComputerName $HvServer -ErrorAction SilentlyContinue
        if (-not $?) {
            throw "Unable to start VM1 $VM1Name after saving it" | Tee-Object -Append -file $summaryLog
        }
        Start-Sleep -s 60
        # get VM1's Memory
        [int64]$vm1AfterAssigned = ($vm1.MemoryAssigned/[int64]1048576)
        [int64]$vm1AfterDemand = ($vm1.MemoryDemand/[int64]1048576)
        if ($vm1AfterAssigned -le 0) {
            $testResult = $resultFail
            throw "$VM1Name Assigned memory is 0 after it started from save" | Tee-Object -Append -file $summaryLog
        }
        if ($vm1AfterDemand -le 0) {
            $testResult = $resultFail
            throw "$VM1Name Memory demand is 0 after it started from save" | Tee-Object -Append -file $summaryLog
        }
        Write-LogInfo "VM1 $VM1Name after assigned memory : $vm1AfterAssigned"
        Write-LogInfo "VM1 $VM1Name after memory demand: $vm1AfterDemand"
        # save VM1 and VM2
        Save-VM $VM1Name -ComputerName $HvServer -ErrorAction SilentlyContinue
        if (-not $?) {
            throw "Unable to save VM1 $VM1Name the second time" | Tee-Object -Append -file $summaryLog
        }
        Save-VM $VM2Name -ComputerName $HvServer -ErrorAction SilentlyContinue
        if (-not $?) {
            throw "Unable to save VM2 $VM2Name the second time" | Tee-Object -Append -file $summaryLog
        }
        Start-VM -Name $VM2Name -ComputerName $HvServer -ErrorAction SilentlyContinue
        if (-not $?) {
            throw "Unable to start VM2 $VM2Name after saving it the second time" | Tee-Object -Append -file $summaryLog
        }
        Start-VM -Name $VM1Name -ComputerName $HvServer -ErrorAction SilentlyContinue
        if (-not $?) {
            throw "Unable to start VM1 $VM1Name after saving it the second time" | Tee-Object -Append -file $summaryLog
        }
        Start-Sleep -s 60
        # get VM1's Memory after saving the VM1
        [int64]$vm1EndAssigned = ($vm1.MemoryAssigned/[int64]1048576)
        [int64]$vm1EndDemand = ($vm1.MemoryDemand/[int64]1048576)
        if ($vm1EndAssigned -le 0) {
            $testResult = $resultFail
            throw "$VM1Name Assigned memory is 0 after last round of saving" | Tee-Object -Append -file $summaryLog
        }
        if ($vm1EndDemand -le 0) {
            $testResult = $resultFail
            throw "$VM1Name Memory demand is 0 after last round of saving" | Tee-Object -Append -file $summaryLog
        }
        Write-LogInfo "VM1 $VM1Name end assigned memory : $vm1EndAssigned"
        Write-LogInfo "VM1 $VM1Name end memory demand: $vm1EndDemand"
        # get VM2's Memory after saving the VM2
        [int64]$vm2EndAssigned = ($vm2.MemoryAssigned/[int64]1048576)
        [int64]$vm2EndDemand = ($vm2.MemoryDemand/[int64]1048576)
        if ($vm2EndAssigned -le 0) {
            $testResult = $resultFail
            throw "$VM2Name Assigned memory is 0 after last round of saving" | Tee-Object -Append -file $summaryLog
        }
        if ($vm2EndDemand -le 0) {
            $testResult = $resultFail
            throw "$VM2Name Memory demand is 0 after last round of saving" | Tee-Object -Append -file $summaryLog
        }
        Write-LogInfo "VM2 $VM2Name end assigned memory : $vm2EndAssigned"
        Write-LogInfo "VM2 $VM2Name end memory demand: $vm2EndDemand"
        Write-LogInfo " DM SaveRestore completed successfully"
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
