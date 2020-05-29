# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

param([String] $TestParams,
      [object] $AllVmData)

function Main {
    Write-LogInfo "Generating constants.sh ..."
    $constantsFile = "$LogDir\constants.sh"
    Set-Content -Value "VM_Size=$($allVmData.InstanceSize)" -Path $constantsFile
    Write-LogInfo "constants.sh created successfully..."

    Copy-RemoteFiles -uploadTo $allVmData.PublicIP -port $allVmData.SSHPort `
        -files "$constantsFile" -username $user -password $password -upload
    #
    # Run the guest VM side script
    #
    try {
        Run-LinuxCmd -username $user -password $password -ip $allVmData.PublicIP -port $allVmData.SSHPort `
            "bash LSVMBUS.sh" -runAsSudo | Out-Null

        $status = Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort `
            -username $user -password $password -command "cat state.txt"
        Copy-RemoteFiles -downloadFrom $allVMData.PublicIP -port $allVMData.SSHPort `
            -username $user -password $password -download `
            -downloadTo $LogDir -files "*.txt, *.log"
        if ($status -imatch "TestFailed") {
            Write-LogErr "Test failed."
            $testResult = "FAIL"
        }   elseif ($status -imatch "TestAborted") {
            Write-LogErr "Test Aborted."
            $testResult = "ABORTED"
        }   elseif ($status -imatch "TestSkipped") {
            Write-LogErr "Test Skipped."
            $testResult = "SKIPPED"
        }   elseif ($status -imatch "TestCompleted") {
            Write-LogInfo "Test Completed."
            $testResult = "PASS"
        }   else {
            Write-LogErr "Test execution is not successful, check test logs in VM."
            $testResult = "ABORTED"
        }
    } catch {
        $ErrorMessage =  $_.Exception.Message
        $ErrorLine = $_.InvocationInfo.ScriptLineNumber
        Write-LogErr "EXCEPTION : $ErrorMessage at line: $ErrorLine"
        $testResult = "FAIL"
    } finally {
        if (!$testResult) {
            $testResult = "ABORTED"
        }
    }
    Write-LogInfo "Test result: $testResult"
    return $testResult
}

Main