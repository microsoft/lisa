# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
param([object] $AllVmData, [object] $CurrentTestData)

function Main {
    param([object] $AllVMData, [object] $CurrentTestData)
    # Create test result
    $currentTestResult = Create-TestResultObject
    $resultArr = @()

    try {
        $testScript = "BVT-VERIFY-SSHD-CONFIG.py"

        Copy-RemoteFiles -uploadTo $AllVMData.PublicIP -port $AllVMData.SSHPort -files $currentTestData.files -username $user -password $password -upload
        Run-LinuxCmd -username $user -password $password -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -command "chmod +x *" -runAsSudo | Out-Null

        Write-LogInfo "Executing : ${testScript}"
        $output=Run-LinuxCmd -username $user -password $password -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -command "python ${testScript}" -runAsSudo
        Run-LinuxCmd -username $user -password $password -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -command "mv Runtime.log ${testScript}.log" -runAsSudo | Out-Null
        Copy-RemoteFiles -download -downloadFrom $AllVMData.PublicIP -files "/home/$user/state.txt, /home/$user/Summary.log, /home/$user/${testScript}.log" -downloadTo $LogDir -port $AllVMData.SSHPort -username $user -password $password
        $testResult = Get-Content $LogDir\Summary.log
        $testStatus = Get-Content $LogDir\state.txt
        Write-LogInfo "Test result : $testResult"

        if ($output -imatch "CLIENT_ALIVE_INTERVAL_SUCCESS") {
            Write-LogInfo "SSHD-CONFIG INFO :Client_Alive_Interval time is 180 Second"
        } else {
            if ($output -imatch "CLIENT_ALIVE_INTERVAL_FAIL") {
                Write-LogInfo "SSHD-CONFIG INFO :There is no Client_Alive_Interval time is 180 Second"
            }
            if ($output -imatch "CLIENT_ALIVE_INTERVAL_COMMENTED") {
                Write-LogInfo "SSHD-CONFIG INFO :There is a commented line in CLIENT_INTERVAL_COMMENTED "
            }
        }

        if ($testStatus -eq "TestCompleted") {
            Write-LogInfo "Test Completed"
        }
    } catch {
        $ErrorMessage =  $_.Exception.Message
        $ErrorLine = $_.InvocationInfo.ScriptLineNumber
        Write-LogInfo "EXCEPTION : $ErrorMessage at line: $ErrorLine"
    } finally {
        if (!$testResult) {
            $testResult = "Aborted"
        }
        $resultArr += $testResult
    }

    $currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
    return $currentTestResult.TestResult
}

Main -AllVMData $AllVmData -CurrentTestData $CurrentTestData
