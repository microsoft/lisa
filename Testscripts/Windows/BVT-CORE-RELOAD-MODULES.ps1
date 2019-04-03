########################################################################
#
# Linux on Hyper-V and Azure Test Code, ver. 1.0.0
# Copyright (c) Microsoft Corporation
#
# All rights reserved.
# Licensed under the Apache License, Version 2.0 (the ""License"");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
#
# THIS CODE IS PROVIDED *AS IS* BASIS, WITHOUT WARRANTIES OR CONDITIONS
# OF ANY KIND, EITHER EXPRESS OR IMPLIED, INCLUDING WITHOUT LIMITATION
# ANY IMPLIED WARRANTIES OR CONDITIONS OF TITLE, FITNESS FOR A PARTICULAR
# PURPOSE, MERCHANTABLITY OR NON-INFRINGEMENT.
#
# See the Apache Version 2.0 License for specific language governing
# permissions and limitations under the License.
#
########################################################################

#########################################################################
# Check test result
########################################################################
param([String] $TestParams,
      [object] $AllVmData,
      [object] $CurrentTestData)

function Check-Result {
    param (
        [String] $VmIp,
        [String] $VMPort,
        [String] $User,
        [String] $Password
    )

    $retVal = $False
    $testRunning = "TestRunning"
    $testCompleted = "TestCompleted"
    $testAborted = "TestAborted"
    $testFailed = "TestFailed"
    $testSkipped = "TestSkipped"
    $attempts = 1

    $timeout = New-Timespan -Minutes 180
    $sw = [diagnostics.stopwatch]::StartNew()
    while ($sw.elapsed -lt $timeout){
        Start-Sleep -s 20
        Write-LogInfo "Test is running. Attempt number ${attempts} to reach VM"
        $attempts++
        $isVmAlive = Is-VmAlive -AllVMDataObject $AllVMData
        if ($isVmAlive -eq "True") {
            $state = Run-LinuxCmd -ip $VmIp -port $VMPort -username $User -password $Password -command "cat state.txt" -ignoreLinuxExitCode:$true
            if (-not $state) {
                if ($TestPlatform -eq "HyperV" -and (Get-VMIntegrationService $VMName -ComputerName $HvServer | `
                    ?{$_.name -eq "Heartbeat"}).PrimaryStatusDescription `
                    -match "No Contact|Lost Communication") {

                    Stop-VM -Name $VMName -ComputerName $HvServer -Force -TurnOff
                    Write-LogErr "Lost Communication or No Contact to VM!"
                    break
                } else {
                    Write-LogInfo "Current VM is inaccessible, please wait for a while."
                }
            } else {
                if ($state -eq $testRunning){
                    Write-LogInfo "Test is still running!"
                } elseif (($state -eq $testCompleted) -or ($state -eq $testSkipped)) {
                    Write-LogInfo "state file contains ${state}"
                    $retVal = $True
                    break
                } elseif (($state -eq $testAborted) -or ($state -eq $testFailed)) {
                    Write-LogErr "state file contains ${state}"
                    break
                }
            }
        } else {
            Write-LogInfo "Current VM is inaccessible, please wait for a while."
        }
    }
    if ($sw.elapsed -ge $timeout) {
        Write-LogErr "Test has timed out. After 3 hours, state file couldn't be read!"
    }
    Collect-TestLogs -LogsDestination $LogDir -ScriptName `
        $CurrentTestData.files.Split('\')[3].Split('.')[0] -TestType "sh" -PublicIP `
        $VmIp -SSHPort $VMPort -Username $User -password $Password -TestName `
        $CurrentTestData.testName | Out-Null
    return $retVal
}

#######################################################################
# Main script body
#######################################################################
function Main {
    param (
        $Ipv4,
        $VMPort,
        $VMUserName,
        $VMPassword,
        $RootDir
    )
    $testScript = "BVT-CORE-RELOAD-MODULES.sh"

    # Run test script in background
    Run-LinuxCmd -username $VMUserName -password $VMPassword -ip $Ipv4 -port $VMPort `
        -command "echo '${VMPassword}' | sudo -S -s eval `"export HOME=``pwd``;bash ${testScript} > BVT-CORE-RELOAD-MODULES_summary.log`"" -RunInBackGround | Out-Null

    $sts = Check-Result -VmIp $Ipv4 -VmPort $VMPort -User $VMUserName -Password $VMPassword
    if (-not $($sts[-1])) {
        Write-LogErr "Something went wrong during execution of BVT-CORE-RELOAD-MODULES.sh script!"
        return "FAIL"
    } else {
        Write-LogInfo "Test Stress Reload Modules has passed"
        return "PASS"
    }
}

Main -VMName $AllVMData.RoleName -hvServer $TestLocation `
         -ipv4 $AllVMData.PublicIP -VMPort $AllVMData.SSHPort `
         -VMUserName $user -VMPassword $password -RootDir $WorkingDirectory
