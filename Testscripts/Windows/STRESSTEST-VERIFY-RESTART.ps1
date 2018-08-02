# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
$ErrorActionPreference = "Continue"

function Main {
    param(
        [parameter(Mandatory=$true)]
        [String] $Distro,
        [parameter(Mandatory=$true)]
        [xml] $XmlConfig
    )

    $result = ""
    $testResult = ""
    $resultArr = @()

    foreach ($param in $currentTestData.TestParameters.param) {
        $paramName = $param.Split("=")[0]
        $paramValue = $param.Split("=")[1]
        if ($paramName -eq "rebootNumber") {
            $rebootNumber = $paramValue
        }
    }
    if (-not $rebootNumber) {
        $rebootNumber = "1"
    }
    for ($rebootNr = 1; $rebootNr -le $rebootNumber; $rebootNr++) {
        try {
            $hs1VIP = $AllVMData.PublicIP
            $hs1vm1sshport = $AllVMData.SSHPort
            $hs1ServiceUrl = $AllVMData.URL
            $hs1vm1Dip = $AllVMData.InternalIP
            LogMsg ("Trying to restart {0}: {1} / {2} ..." `
                -f @($AllVMData.RoleName, $rebootNr, $rebootNumber))
            $RestartStatus = RestartAllDeployments -allVMData $AllVMData
            if ($RestartStatus -eq "True") {
                $isSSHOpened = isAllSSHPortsEnabledRG -AllVMDataObject $AllVMData
                if ($isSSHOpened -eq "True") {
                    $isRestarted = $true
                } else {
                    LogErr "VM is not available after restart"
                    $isRestarted = $false
                }
            } else {
                $isRestarted = $false
            }
            if ($isRestarted) {
                LogMsg "Virtual machine restart successful."
                $testResult = "PASS"
            } else {
                LogErr "Virtual machine restart failed."
                $testResult = "FAIL"
                break
            }
        } catch {
            $ErrorMessage =  $_.Exception.Message
            $ErrorLine = $_.InvocationInfo.ScriptLineNumber
            LogMsg "EXCEPTION : $ErrorMessage at line: $ErrorLine"
            break
        } finally {
            if (-not $testResult) {
                $testResult = "Aborted"
            }
            $resultArr += $testResult
        }
    }
    LogMsg "Reboot Stress Test Result: $rebootNr/$rebootNumber"
    if (($rebootNr - 1) -lt $rebootNumber) {
        $testResult = "FAIL"
    }

    $result = GetFinalResultHeader -resultarr $resultArr
    # Return the result and summary to the test suite script..
    return $result
}

# Global Variables
#
# $currentTestData
# $Distro
# $XmlConfig
# $AllVMData

Main -Distro $Distro -XmlConfig $xmlConfig 
