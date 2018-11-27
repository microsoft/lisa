# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Synopsis
    Add a value to a guest VM from the host.

.Description
    Use WMI to add a key value pair to the KVP Pool 0 on guest
    a Linux guest VM.
#>

param([string] $TestParams)

function Main {
    param (
        $VMName,
        $HvServer,
        $RootDir,
        $TestParams
    )

    $key = $null
    $value = $null

    if (-not $TestParams) {
        Write-LogErr "Error: No TestParams provided"
        Write-LogErr "This script requires the Key & value as the test parameters"
        return "Aborted"
    }
    if (-not $RootDir) {
        Write-LogInfo "Warn : No RootDir test parameter was provided"
    } else {
        Set-Location $RootDir
    }

    $params = $TestParams.Split(";")
    foreach ($p in $params) {
        $fields = $p.Split("=")

        if ($fields[0].Trim() -eq "Key") {
            $key = $fields[1].Trim()
        }
        if ($fields[0].Trim() -eq "Value") {
            $value = $fields[1].Trim()
        }
    }

    if (-not $key) {
        Write-LogErr "Error: Missing testParam Key to be added"
        return "FAIL"
    }
    if (-not $value) {
        Write-LogErr "Error: Missing testParam Value to be added"
        return "FAIL"
    }

    Write-LogInfo "Info : Adding Key=value of: ${key}=${value}"

    # Add the Key Value pair to the Pool 0 on guest OS.
    $vmManagementService = Get-WmiObject -class "Msvm_VirtualSystemManagementService" `
        -namespace "root\virtualization\v2" -ComputerName $HvServer
    if (-not $vmManagementService) {
        Write-LogErr "Error: Unable to create a VMManagementService object"
        return "FAIL"
    }

    $vmGuest = Get-WmiObject -Namespace root\virtualization\v2 -ComputerName $HvServer `
        -Query "Select * From Msvm_ComputerSystem Where ElementName='$VMName'"
    if (-not $vmGuest) {
        Write-LogErr "Error: Unable to create VMGuest object"
        return "FAIL"
    }

    $msvmKvpExchangeDataItemPath = "\\$HvServer\root\virtualization\v2:Msvm_KvpExchangeDataItem"
    $msvmKvpExchangeDataItem = ([WmiClass]$msvmKvpExchangeDataItemPath).CreateInstance()
    if (-not $msvmKvpExchangeDataItem) {
        Write-LogErr "Error: Unable to create Msvm_KvpExchangeDataItem object"
        return "FAIL"
    }

    # Populate the Msvm_KvpExchangeDataItem object
    $msvmKvpExchangeDataItem.Source = 0
    $msvmKvpExchangeDataItem.Name = $key
    $msvmKvpExchangeDataItem.Data = $value

    # Set the KVP value on the guest
    $result = $vmManagementService.AddKvpItems($vmGuest, $msvmKvpExchangeDataItem.PSBase.GetText(1))
    $job = [wmi]$result.Job
    while($job.jobstate -lt 7) {
        $job.get()
    }
    if ($job.ErrorCode -ne 0) {
        Write-LogErr "Error: Unable to add KVP value to guest"
        Write-LogErr "       error code $($job.ErrorCode)"
        return "FAIL"
    }
    if ($job.Status -ne "OK") {
        Write-LogErr "Error: KVP add job did not complete with status OK"
        return "FAIL"
    }

    Write-LogInfo "Info : KVP item added successfully on guest"
    return "PASS"
}

Main -VMName $AllVMData.RoleName -HvServer $xmlConfig.config.Hyperv.Hosts.ChildNodes[0].ServerName `
        -RootDir $WorkingDirectory -TestParams $TestParams
