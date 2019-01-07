# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

function Main {
    # Create test result
    $currentTestResult = Create-TestResultObject
    $resultArr = @()

    try {
        Provision-VMsForLisa -allVMData $allVMData -installPackagesOnRoleNames "none"
        Copy-RemoteFiles -uploadTo $allVMData.PublicIP -port $allVMData.SSHPort -files $currentTestData.files -username "root" -password $password -upload

        $constantsFile = Join-Path $env:TEMP "xfstests-config.config"
        Write-LogInfo "Generating $constantsFile ..."
        Set-Content -Value "" -Path $constantsFile -NoNewline
        foreach ($param in $currentTestData.TestParameters.param) {
            if ($param -imatch "FSTYP=") {
                $TestFileSystem = ($param.Replace("FSTYP=",""))
                Add-Content -Value "[$TestFileSystem]" -Path $constantsFile
                Write-LogInfo "[$TestFileSystem] added to constants.sh"
            }
            Add-Content -Value "$param" -Path $constantsFile
            Write-LogInfo "$param added to constants.sh"
        }
        Write-LogInfo "$constantsFile created successfully..."
        Copy-RemoteFiles -uploadTo $allVMData.PublicIP -port $allVMData.SSHPort -files $constantsFile -username "root" -password $password -upload

        $null = Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username "root" -password $password -command "chmod +x *.sh"
        $testJob = Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username "root" -password $password -command "/root/perf_xfstesting.sh -TestFileSystem $TestFileSystem" -RunInBackground

        # region MONITOR TEST
        while ((Get-Job -Id $testJob).State -eq "Running") {
            $currentStatus = Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username "root" -password $password -command "tail -1 XFSTestingConsole.log"
            Write-LogInfo "Current Test Status : $currentStatus"
            Wait-Time -seconds 20
        }
        Copy-RemoteFiles -download -downloadFrom $allVMData.PublicIP -files "XFSTestingConsole.log" -downloadTo $LogDir -port $allVMData.SSHPort -username "root" -password $password
        $XFSTestingConsole = Get-Content "$LogDir\XFSTestingConsole.log"

        if ($XFSTestingConsole -imatch "Passed all") {
            $testResult = "PASS"
        } else {
            $testResult = "FAIL"
        }

        foreach ( $line in $XFSTestingConsole.Split("`n")) {
            Write-LogInfo "$line"
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