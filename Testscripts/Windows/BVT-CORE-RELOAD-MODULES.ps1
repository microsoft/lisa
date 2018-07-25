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
        [String] $VmPort,
        [String] $User,
        [String] $Password
    )

    $retVal = $False
    $stateFile = "${LogDir}\state.txt"
    $testCompleted = "TestCompleted"
    $testAborted = "TestAborted"
    $testFailed = "TestFailed"
    $attempts = 200

    while ($attempts -ne 0 ){
        RemoteCopy -download -downloadFrom $VmIp -files "/home/${User}/state.txt" -downloadTo $LogDir -port $VmPort -username "root" -password $Password
        $sts = $?
            if (Test-Path $stateFile){
                $contents = Get-Content -Path $stateFile
                if ($null -ne $contents){
                    if ($contents -eq $testCompleted) {
                        LogMsg "Info: state file contains TestCompleted"
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
    $currentTestResult = CreateTestResultObject
    $resultArr = @()
    $testScript = "BVT-CORE-RELOAD-MODULES.sh"
    $ipv4 = $AllVMData.PublicIP
    $vmPort = $AllVMData.SSHPort

    LogMsg "This script covers test case: ${TC_COVERED}"

    # Start pinging the VM while the netvsc driver is being stress reloaded
    $pingJob = Start-Job -ScriptBlock { param($ipv4) ping -t $ipv4 } -ArgumentList ($ipv4)
    if (-not $?) {
        LogErr "Error: Unable to start job for pinging the VM while stress reloading the netvsc driver."
        $testResult = "FAIL"
        $resultArr += $testResult
        $currentTestResult.TestResult = GetFinalResultHeader -resultarr $resultArr
        return $currentTestResult.TestResult 
    }

    # Run test script in background
    RunLinuxCmd -username $user -password $password -ip $ipv4 -port $vmPort -command "echo '${password}' | sudo -S -s eval `"export HOME=``pwd``;bash ${testScript} > BVT-CORE-RELOAD-MODULES_summary.log`"" -RunInBackGround

    Stop-Job $pingJob

    $sts = Check-Result -VmIp $ipv4 -VmPort $vmPort -User $user -Password $password
    if (-not $($sts[-1])) {
        LogErr "Error: Something went wrong during execution of BVT-CORE-RELOAD-MODULES.sh script!" 
        $testResult = "FAIL"
        $resultArr += $testResult
        $currentTestResult.TestResult = GetFinalResultHeader -resultarr $resultArr
        return $currentTestResult.TestResult 
    } else {
        LogMsg "Info : Test Stress Reload Modules ${results} "
        $testResult = "PASS"
        $resultArr += $testResult
        $currentTestResult.TestResult = GetFinalResultHeader -resultarr $resultArr
        return $currentTestResult.TestResult
    }
}

Main
