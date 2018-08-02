# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

function Main {
    # Create test result 
    $result = ""
    $currentTestResult = CreateTestResultObject
    $resultArr = @()

    try {
        ProvisionVMsForLisa -allVMData $allVMData -installPackagesOnRoleNames "none"
        RemoteCopy -uploadTo $allVMData.PublicIP -port $allVMData.SSHPort -files $currentTestData.files -username "root" -password $password -upload
        
        $constantsFile = ".\Temp\xfstests-config.config"
        LogMsg "Generating $constantsFile ..."
        Set-Content -Value "" -Path $constantsFile -NoNewline
        foreach ($param in $currentTestData.TestParameters.param) {
            if ($param -imatch "FSTYP=") {
                $TestFileSystem = ($param.Replace("FSTYP=",""))
                Add-Content -Value "[$TestFileSystem]" -Path $constantsFile
                LogMsg "[$TestFileSystem] added to constants.sh"
            }
            Add-Content -Value "$param" -Path $constantsFile
            LogMsg "$param added to constants.sh"
        }
        LogMsg "$constantsFile created successfully..."
        RemoteCopy -uploadTo $allVMData.PublicIP -port $allVMData.SSHPort -files $constantsFile -username "root" -password $password -upload

        $out = RunLinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username "root" -password $password -command "chmod +x *.sh"
        $testJob = RunLinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username "root" -password $password -command "/root/perf_xfstesting.sh -TestFileSystem $TestFileSystem" -RunInBackground

        # region MONITOR TEST
        while ((Get-Job -Id $testJob).State -eq "Running") {
            $currentStatus = RunLinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username "root" -password $password -command "tail -1 XFSTestingConsole.log"
            LogMsg "Current Test Staus : $currentStatus"
            WaitFor -seconds 20
        }
        RemoteCopy -download -downloadFrom $allVMData.PublicIP -files "XFSTestingConsole.log" -downloadTo $LogDir -port $allVMData.SSHPort -username "root" -password $password
        $XFSTestingConsole = Get-Content "$LogDir\XFSTestingConsole.log"
        
        if ($XFSTestingConsole -imatch "Passed all") {
            $testResult = "PASS"
        } else {
            $testResult = "FAIL"
        }

        foreach ( $line in $XFSTestingConsole.Split("`n")) {
            LogMsg "$line"
        }
    } catch {
        $ErrorMessage =  $_.Exception.Message
        $ErrorLine = $_.InvocationInfo.ScriptLineNumber
        LogMsg "EXCEPTION : $ErrorMessage at line: $ErrorLine"
    } finally {
        $metaData = ""
        if (!$testResult) {
            $testResult = "Aborted"
        }
        $resultArr += $testResult
    }

    $currentTestResult.TestResult = GetFinalResultHeader -resultarr $resultArr
    return $currentTestResult.TestResult  
}

Main
