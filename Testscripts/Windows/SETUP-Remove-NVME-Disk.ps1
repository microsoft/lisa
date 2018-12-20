# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Description
    This cleanup script removes all the NVME devices attached to
    a VM.
#>

param(
    [String] $TestParams
)

function Main {
    param (
        $TestParams
    )

    try {
        $testResult = $null

        # Remove NVME disks from any VM that might use them
        Stop-HyperVGroupVMs $allVmData[0].HyperVGroupName $allVmData[0].HyperVHost
        $usedNvmeDisks = Get-VMAssignableDevice *
        foreach ($nvmeDisk in $usedNvmeDisks) {
            $vmNameWithNvme = $nvmeDisk.VMName
            $locationPath = $nvmeDisk.LocationPath
            Remove-VMAssignableDevice -LocationPath $locationPath `
                -VMName $vmNameWithNvme
            if (-not $?) {
                throw "Error: Unable to remove NVME disk (VM: $vmNameWithNvme `
                    : LocationPath $locationPath)"
            }
        }
        $testResult = "PASS"
    } catch {
        $ErrorMessage = $_.Exception.Message
        $ErrorLine = $_.InvocationInfo.ScriptLineNumber
        Write-LogErr "EXCEPTION : $ErrorMessage at line: $ErrorLine"
    } finally {
        if (!$testResult) {
            $testResult = "ABORTED"
        }
        $resultArr += $testResult
    }
    $currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
    return $currentTestResult.TestResult
}

Main -TestParams (ConvertFrom-StringData $TestParams.Replace(";","`n"))