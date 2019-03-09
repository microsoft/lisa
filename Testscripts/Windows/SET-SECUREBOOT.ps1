# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
<#
.Synopsis
    This script enables Secure Boot features of a Generation 2 VM.

.Description
    This setup script will enable the Secure Boot features of a Generation 2 VM.
#>
param([object] $AllVMData)

$ErrorActionPreference = "Stop"
function Main {
    $currentTestResult = Create-TestResultObject
    $resultArr = @()
    try
    {
        $testResult = $null
        $captureVMData = $allVMData
        $VMName = $captureVMData.RoleName
        $HvServer= $captureVMData.HyperVhost
        # Check if the VM VHD in not on the same drive as the backup destination
        $vm = Get-VM -Name $VMName -ComputerName $HvServer
        #
        # Check if it's a Generation 2 VM
        #
        if ($vm.Generation -ne 2) {
            throw "VM ${VMName} is not a Generation 2 VM"
        }
        #
        # Check if Secure Boot is enabled
        #
        Write-LogInfo "Checking SecureBoot is enabled or not"
        $firmwareSettings = Get-VMFirmware -VMName $VMName -ComputerName $HvServer
        if ($firmwareSettings.SecureBoot -ne "On") {
            Set-VMFirmware -VMName $VMName -EnableSecureBoot On
            if (-not $?) {
                throw "Unable to enable secure boot!"
            }
            Write-LogInfo "Successfully Enabled SecureBoot"
        }
        Write-LogInfo "Setting SecureBoot template"
        $null = Set-VMFirmware -VMName $VMName -ComputerName $HvServer -SecureBootTemplate MicrosoftUEFICertificateAuthority
        if (-not $?) {
            throw "Unable to set secure boot template!"
        }
        Write-LogInfo "Secure Boot: $($firmwareSettings.SecureBoot), Secure Boot Template: $($firmwareSettings.SecureBootTemplate)"
        $testResult = $resultPass
    } catch {
        $ErrorMessage =  $_.Exception.Message
        $ErrorLine = $_.InvocationInfo.ScriptLineNumber
        Write-LogErr "$ErrorMessage at line: $ErrorLine"
    } finally {
        if (!$testResult) {
            $testResult = $resultAborted
        }
        $resultArr += $testResult
    }
    $currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
    return $currentTestResult.TestResult
}
Main
