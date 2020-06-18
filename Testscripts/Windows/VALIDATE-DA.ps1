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
        $VMName,
        $Ipv4,
        $VMPort,
        $VMUserName,
        $VMPassword
    )

    $remoteScript = "validate-da.sh"
    #######################################################################
    #
    #	Main body script
    #
    #######################################################################

    # Checking the input arguments
    if (-not $VMName) {
        Write-LogErr "VM name is null!"
        return "FAIL"
    }

    Run-LinuxCmd -username $VMUserName -password $VMPassword -ip $Ipv4 -port $VMPort $remoteScript -runAsSudo
    $testResult = Collect-TestLogs -LogsDestination $LogDir -ScriptName $remoteScript.split(".")[0] -TestType "sh" `
        -PublicIP $Ipv4 -SSHPort $VMPort -Username $VMUserName -password $VMPassword `
        -TestName $currentTestData.testName
    $resultArr += $testResult
    Write-LogInfo "Test result : $testResult"
    $currentTestResult = Create-TestResultObject
    $currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
    return $currentTestResult
}
Main -VMName $AllVMData.RoleName `
    -Ipv4 $AllVMData.PublicIP -VMPort $AllVMData.SSHPort `
    -VMUserName $user -VMPassword $password
