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
        LogErr "Error: No TestParams provided"
        LogErr "This script requires the Key & value as the test parameters"
        return "Aborted"
    }
    if (-not $RootDir) {
        LogMsg "Warn : No RootDir test parameter was provided"
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
        LogErr "Error: Missing testParam Key to be added"
        return "FAIL"
    }
    if (-not $value) {
        LogErr "Error: Missing testParam Value to be added"
        return "FAIL"
    }

    LogMsg "Info : Adding Key=value of: ${key}=${value}"

    # Add the Key Value pair to the Pool 0 on guest OS.
    $vmManagementService = Get-WmiObject -class "Msvm_VirtualSystemManagementService" `
        -namespace "root\virtualization\v2" -ComputerName $HvServer
    if (-not $vmManagementService) {
        LogErr "Error: Unable to create a VMManagementService object"
        return "FAIL"
    }

    $vmGuest = Get-WmiObject -Namespace root\virtualization\v2 -ComputerName $HvServer `
        -Query "Select * From Msvm_ComputerSystem Where ElementName='$VMName'"
    if (-not $vmGuest) {
        LogErr "Error: Unable to create VMGuest object"
        return "FAIL"
    }

    $msvmKvpExchangeDataItemPath = "\\$HvServer\root\virtualization\v2:Msvm_KvpExchangeDataItem"
    $msvmKvpExchangeDataItem = ([WmiClass]$msvmKvpExchangeDataItemPath).CreateInstance()
    if (-not $msvmKvpExchangeDataItem) {
        LogErr "Error: Unable to create Msvm_KvpExchangeDataItem object"
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
        LogErr "Error: Unable to add KVP value to guest"  
        LogErr "       error code $($job.ErrorCode)"
        return "FAIL"
    }
    if ($job.Status -ne "OK") {
        LogErr "Error: KVP add job did not complete with status OK"
        return "FAIL"
    }

    LogMsg "Info : KVP item added successfully on guest" 
    return "PASS"
}

Main -VMName $AllVMData.RoleName -HvServer $xmlConfig.config.Hyperv.Host.ServerName `
        -RootDir $WorkingDirectory -TestParams $TestParams