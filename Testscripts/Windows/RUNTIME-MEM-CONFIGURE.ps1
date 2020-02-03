# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
<#
.Synopsis
	Configure Runtime Memory Resize for a given VM.
#>
param([string] $testParams, [object] $AllVmData)
function Main
{
    param (
        $testParams, $allVMData
    )
    $currentTestResult = Create-TestResultObject
    try {
        $testResult = $null
        $captureVMData = $allVMData
        $vmName = $captureVMData.RoleName
        $HvServer= $captureVMData.HyperVhost
        # No dynamic memory needed; set false as default
        $DM_Enabled = $False
        # Assign startupMem with 0
        [int64]$startupMem = 0
        Write-LogInfo "To Check the host build number"
        $BuildNumber = Get-HostBuildNumber $captureVMData.HyperVhost
        Write-LogInfo "Host build number : '$BuildNumber'"
        if ($buildNumber -eq 0) {
            throw "Invalid Windows build number"
        } elseif ($BuildNumber -lt 10500) {
            $testResult = "ABORTED"
            Throw "Feature supported only on WS2016 and newer"
        }
        Write-LogInfo "startup memory : $($testParams.startupMem)"
        # Parse the TestParams string, then process each parameter
        $startupMem = Convert-ToMemSize $testParams.startupMem $captureVMData.HyperVhost
        if ($startupMem -le 0) {
            throw "Invalid startup memory"
        }
        Write-LogInfo "startupMem: $startupMem"
        # check if we have all variables set
        if ($vmName -and $DM_Enabled -eq $False -and $startupMem) {
            Write-LogInfo "Check VM:'${vmName}' is in running state"
            # make sure VM is off
            if (Get-VM -Name $vmName -ComputerName $HvServer | Where-Object { $_.State -like "Running" }) {
                Write-LogInfo "Stopping VM $vmName"
                Stop-VM -VMName $vmName -ComputerName $HvServer -TurnOff -Force
                if (-not $?) {
                    throw "Unable to shut $vmName down (in order to set Memory parameters)"
                }
                Write-LogInfo "VM $vmName stopped"
                # wait for VM to finish shutting down
                Wait-VMState -VMName $vmName -HvServer $HvServer -VMState "Off"
            }
        }
        Write-LogInfo "To Verify VM Version is greater than 7"
        $version = Get-VM -Name $vmName -ComputerName $HvServer | Select-Object -ExpandProperty Version
        [int]$version = [convert]::ToInt32($version[0], 10)
        if ($version -lt 7) {
            throw  "$vmName is version $version. It needs to be version 7 or greater"
        } elseif($version -gt 7) {
            Write-LogInfo "VM $vmName is version $version"
        }
        #To set VM Memory
        Set-VMMemory -vmName $vmName -ComputerName $hvServer -DynamicMemoryEnabled $DM_Enabled `
                      -StartupBytes $startupMem
        if (-not $?) {
            $testResult = $resultFail
            throw "Unable to set VM Memory for $vmName"
        }
        $testResult = $resultPass
    } catch {
        $ErrorMessage =  $_.Exception.Message
        $ErrorLine = $_.InvocationInfo.ScriptLineNumber
        Write-LogErr "$ErrorMessage at line: $ErrorLine"
    } finally {
        if (!$testResult) {
            $testResult = "ABORTED"
        }
        $resultArr += $testResult
    }
    $currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
    return $currentTestResult.TestResult
}

Main -TestParams (ConvertFrom-StringData $TestParams.Replace(";","`n")) -allVMData $AllVmData
