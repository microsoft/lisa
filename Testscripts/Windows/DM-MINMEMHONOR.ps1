# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Synopsis
 Verify that the assigned memory never drops below the VMs Minimum Memory setting.

 Description:
  Using a VM with dynamic memory enabled, verify the assigned memory never drops below the VMs Minimum Memory setting.
  When VM2 starts, VM1's memory never drops below the Minimum Memory setting.
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

param([String] $TestParams,
      [object] $AllVmData)

#######################################################################
#
# Main script body
#
#######################################################################
#
# Check input arguments
#
function Main {
    param (
        $TestParams, $AllVmData
    )
    $currentTestResult = Create-TestResultObject
    $resultArr = @()
    try {
        $testResult = $null
        $vm1name = $AllVmData[0].RoleName
        $vm2name = $AllVmData[1].RoleName
        $HvServer = $AllVmData[0].HyperVHost
        $VM1Ipv4 = $AllVmData[0].PublicIP
        $VM2Ipv4 = $AllVmData[1].PublicIP
        $VMPort = $AllVmData[0].SSHPort

        # change working directory to root dir
        Set-Location $WorkingDirectory

        Write-LogInfo "VM1name is $vm1name"
        Write-LogInfo "VM2name is $vm2name"
        Write-LogInfo "Hvserver is $HvServer"

        Write-LogInfo "Param vm1 Details are -VM $vm1name -minMem $($TestParams.minMem) -maxMem $($TestParams.maxMem) -startupMem $($TestParams.startupMem) -memWeight $($TestParams.memWeight)"
        Write-LogInfo "Param vm2 Details are -VM $vm2name -minMem $($TestParams.minMem1) -maxMem $($TestParams.maxMem1) -startupMem $($TestParams.startupMem1) -memWeight $($TestParams.memWeight1)"
        Set-VMDynamicMemory -VM $AllVmData[0] -minMem $TestParams.minMem -maxMem $TestParams.maxMem `
            -startupMem $TestParams.startupMem -memWeight $TestParams.memWeight | Out-Null
        Set-VMDynamicMemory -VM $AllVmData[1] -minMem $TestParams.minMem1 -maxMem $TestParams.maxMem1 `
            -startupMem $TestParams.startupMem1 -memWeight $TestParams.memWeight1 | Out-Null

        $vm1 = Get-VM -Name $vm1name -ComputerName $HvServer -ErrorAction SilentlyContinue
        $vm2 = Get-VM -Name $vm2name -ComputerName $HvServer -ErrorAction SilentlyContinue
        Write-LogInfo "Starting VM1 $vm1name"
        $VM1Ipv4 = Start-VMandGetIP $vm1name $HvServer $VMPort $user $password
        Write-LogInfo "IP address of the VM $vm1name is $VM1Ipv4"

        for($i=1; $i -le 10; $i++) {
            Write-LogInfo "Attempt to start VM2 $vm2name for $i time(s)"
            $VM2Ipv4 = Start-VMandGetIP $vm2name $HvServer $VMPort $user $password
            if($False -eq $VM2Ipv4) {
                Start-Sleep -Seconds 20
                continue
            } else {
                Write-LogInfo "IP address of the VM $vm2name is $VM2Ipv4"
                break
            }
        }
        if (($False -eq $VM2Ipv4) -and ($i -gt 11)) {
            Throw "Error: $vm2name not start after 11 tries"
        }
        # Get VM's minimum memory setting
        [int64]$vm1MinMem = ($vm1.MemoryMinimum/1MB)
        # get memory stats from vm1 and vm2
        # wait up to 2 min for it
        $sleepPeriod = 80
        # get VM1 and VM2's Memory
        $count = 1
        while ($sleepPeriod -gt 0)  {
            Write-LogInfo "======================== the $count time(s) check ========================"
            [int64]$vm1Assigned = ($vm1.MemoryAssigned / 1MB)
            [int64]$vm1Demand = ($vm1.MemoryDemand / 1MB)
            [int64]$vm2Assigned = ($vm2.MemoryAssigned / 1MB)
            [int64]$vm2Demand = ($vm2.MemoryDemand / 1MB)
            Write-LogInfo "VM Name ${vm1Name} vm1assigned is $vm1Assigned MB"
            Write-LogInfo "Minimum memory for $vm1Name is $vm1MinMem MB"
            Write-LogInfo "${vm1Name} vm1Demand is $vm1Demand MB"
            Write-LogInfo "${vm2Name} vm2Assigned is $vm2Assigned MB"
            Write-LogInfo "${vm2Name} vm2Demand is $vm2Demand MB"
            if ($vm1Assigned -lt $vm1MinMem) {
                Throw "Error: $vm1Name assigned memory drops below minimum memory set, $vm1MinMem MB"
            }
            $sleepPeriod -= 20
            Start-Sleep -Seconds 20
            $count += 1
        }
        if (($vm1Assigned -le 0) -or ($vm1Demand -le 0) -or ($vm2Assigned -le 0) -or ($vm2Demand -le 0)) {
            Throw "Error: vm1 or vm2 reported 0 memory (assigned or demand)."
        }
        Write-LogInfo "Memory stats after both $vm1Name and $vm2Name started reporting "
        Write-LogInfo "  ${vm1Name}: assigned - $vm1Assigned | demand - $vm1Demand"
        Write-LogInfo "  ${vm2Name}: assigned - $vm2Assigned | demand - $vm2Demand"
        Write-LogInfo "$vm1Name assigned memory never drops below the VMs Minimum Memory setting, $vm1MinMem MB"
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
Main -TestParams (ConvertFrom-StringData $TestParams.Replace(";","`n")) -AllVmData $AllVmData
