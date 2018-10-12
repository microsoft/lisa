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
function Check-Result {
    param (
        [String] $VmIp,
        [String] $VMPort,
        [String] $User,
        [String] $Password
    )

    $retVal = $False
    $stateFile = "${LogDir}\state.txt"
    $testCompleted = "TestCompleted"
    $testAborted = "TestAborted"
    $testFailed = "TestFailed"
    $testSkipped = "TestSkipped"
    $attempts = 200

    while ($attempts -ne 0 ){
        RemoteCopy -download -downloadFrom $VmIp -files "/home/${User}/state.txt" -downloadTo $LogDir -port $VMPort -username $User -password $Password
            if (Test-Path $stateFile){
                $contents = Get-Content -Path $stateFile
                if ($null -ne $contents){
                    if (($contents -eq $testCompleted) -or ($contents -eq $testSkipped)) {
                        LogMsg "Info: state file contains ${contents}"
                        $retVal = $True
                        break
                    }
                    if (($contents -eq $testAborted) -or ($contents -eq $testFailed)) {
                        LogErr "Info: State file contains TestAborted or TestFailed"
                        break
                    }
                }
                else {
                    LogMsg "Warning: state file is empty!"
                    break
                }
            }

        else {
            Start-Sleep -s 10
            $attempts--
            LogMsg "Info : Attempt number ${attempts}"
            LogMsg "LogDir: ${LogDir}"
            LogMsg "StateFile: ${stateFile}"
            if ($TestPlatform -eq "HyperV") {
                if ((Get-VMIntegrationService $VMName -ComputerName $HvServer | ?{$_.name -eq "Heartbeat"}).PrimaryStatusDescription -match "No Contact|Lost Communication") {
                    Stop-VM -Name $VMName -ComputerName $HvServer -Force -TurnOff
                    LogErr "Error : Lost Communication or No Contact to VM, maybe vm reboots"
                    break
                }
            }
            if ($attempts -eq 0) {
                LogErr "Error : Reached max number of attempts to extract state file"
            }
        }

        if (Test-Path $stateFile) {
            Remove-Item $stateFile
        }
    }

    if (Test-Path $stateFile) {
        Remove-Item $stateFile
    }
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

    # Start pinging the VM while the netvsc driver is being stress reloaded
    $pingJob = Start-Job -ScriptBlock { param($Ipv4) ping -t $Ipv4 } -ArgumentList ($Ipv4)
    if (-not $?) {
        LogErr "Error: Unable to start job for pinging the VM while stress reloading the netvsc driver."
        return "FAIL"
    }

    # Run test script in background
    RunLinuxCmd -username $VMUserName -password $VMPassword -ip $Ipv4 -port $VMPort -command "echo '${VMPassword}' | sudo -S -s eval `"export HOME=``pwd``;bash ${testScript} > BVT-CORE-RELOAD-MODULES_summary.log`"" -RunInBackGround

    Stop-Job $pingJob

    $sts = Check-Result -VmIp $Ipv4 -VmPort $VMPort -User $VMUserName -Password $VMPassword
    if (-not $($sts[-1])) {
        LogErr "Error: Something went wrong during execution of BVT-CORE-RELOAD-MODULES.sh script!"
        return "FAIL"
    } else {
        LogMsg "Info : Test Stress Reload Modules ${results}"
        return "PASS"
    }
}

Main -VMName $AllVMData.RoleName -hvServer $TestLocation `
         -ipv4 $AllVMData.PublicIP -VMPort $AllVMData.SSHPort `
         -VMUserName $user -VMPassword $password -RootDir $WorkingDirectory
