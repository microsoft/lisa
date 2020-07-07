# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
<#
.Synopsis
    This script validates Dependency Agent.

.Description
    The script will install the Latest Dependency Agent and validate install/uninstall
    scenarios as well as enable/disable scenarios.
'
#>
param([String] $TestParams,
      [object] $AllVmData)
function Main {
    param (
        [String] $VMName,
        [String] $Ipv4,
        [int] $VMPort,
        [String] $VMUserName,
        [String] $VMPassword
    )

    $remoteScript = "validate-da.sh"
    # timeout accounts for sum of sleep time in the validate-da script. This helps prevent timeout during execution.
    $timeout = 480
    #######################################################################
    #
    #	Main body script
    #
    #######################################################################
    $currentTestResult = Create-TestResultObject
    try {
        # Checking the input arguments
        if ($VMName.length -eq 0) {
            Write-LogErr "VM name is empty!"
            return "FAIL"
        }

        # Running validate-da script
        Run-LinuxCmd -username $VMUserName -password $VMPassword -ip $Ipv4 -port $VMPort -runMaxAllowedTime $timeout -command "sudo bash $remoteScript" -runAsSudo
        $testResult = Collect-TestLogs -LogsDestination $LogDir -ScriptName $remoteScript.split(".")[0] -TestType "sh" `
            -PublicIP $Ipv4 -SSHPort $VMPort -Username $VMUserName -password $VMPassword `
            -TestName $currentTestData.testName
        Write-LogInfo "Test result : $testResult"
    } catch {
        $ErrorMessage = $_.Exception.Message
        $ErrorLine = $_.InvocationInfo.ScriptLineNumber
        Write-LogInfo "EXCEPTION: $ErrorMessage at line: $ErrorLine"
    } finally {
        if (!$testResult) {
            $testResult = "Aborted"
        }
        $resultArr += $testResult
    }
    $currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
    return $currentTestResult
}
Main -VMName $AllVMData.RoleName `
    -Ipv4 $AllVMData.PublicIP -VMPort $AllVMData.SSHPort `
    -VMUserName $user -VMPassword $password
