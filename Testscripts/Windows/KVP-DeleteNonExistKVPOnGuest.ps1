# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Synopsis
    Try to Delete a Non-Exist KVP item from a Linux guest.
.Description
    Try to Delete a Non-Exist KVP item from pool 0 on a Linux guest.
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
    $tcCovered = "Unknown"

    if (-not $TestParams) {
        LogErr "Error: No TestParams provided"
        LogErr "     : This script requires key & value test parameters"
        return "Aborted"
    }
    if (-not $RootDir) {
        LogMsg "Warn : no RootDir test parameter specified"
    } else {
       Set-Location $RootDir
    }

    # Find the TestParams we require.  Complain if not found
    $params = $TestParams.Split(";")
    foreach ($p in $params) {
        $fields = $p.Split("=")
        
        switch ($fields[0].Trim()) {
            "key"        { $key       = $fields[1].Trim() }
            "value"      { $value     = $fields[1].Trim() }
            "tc_covered" { $tcCovered = $fields[1].Trim() }
            default   {}  # unknown param - just ignore it
        }
    } 

    LogMsg "Info : Checking for required test parameters"

    if (-not $key) {
        LogErr "Error: Missing testParam Key to be added"
        return "FAIL"
    }
    if (-not $value) {
        LogErr "Error: Missing testParam Value to be added"
        return "FAIL"
    }

    # Delete the Non-Existing Key Value pair from the Pool 0 on guest OS. If the Key is already present, will return proper message.
    LogMsg "Info : Creating VM Management Service object"
    $vmManagementService = Get-WmiObject -ComputerName $HvServer `
        -class "Msvm_VirtualSystemManagementService" -namespace "root\virtualization\v2"
    if (-not $vmManagementService) {
        LogErr "Error: Unable to create a VMManagementService object"
        return "FAIL"
    }
    $vmGuest = Get-WmiObject -ComputerName $HvServer -Namespace root\virtualization\v2 `
        -Query "Select * From Msvm_ComputerSystem Where ElementName='$VMName'"
    if (-not $vmGuest) {
        LogErr "Error: Unable to create VMGuest object"
        return "FAIL"
    }

    LogMsg "Info : Creating Msvm_KvpExchangeDataItem object"
    $msvmKvpExchangeDataItemPath = "\\$HvServer\root\virtualization\v2:Msvm_KvpExchangeDataItem"
    $msvmKvpExchangeDataItem = ([WmiClass]$msvmKvpExchangeDataItemPath).CreateInstance()
    if (-not $msvmKvpExchangeDataItem) {
        LogErr "Error: Unable to create Msvm_KvpExchangeDataItem object"
        return "FAIL"
    }
    
    LogMsg "Info : Detecting Host version of Windows Server"
    $osInfo = GWMI Win32_OperatingSystem -ComputerName $HvServer
    if (-not $osInfo) {
        LogErr "Error: Unable to collect Operating System information"
        return "FAIL"
    }

    LogMsg "Info : Deleting Key '${key}' from Pool 0"
    $msvmKvpExchangeDataItem.Source = 0
    $msvmKvpExchangeDataItem.Name = $Key
    $msvmKvpExchangeDataItem.Data = $Value
    $result = $vmManagementService.RemoveKvpItems($vmGuest, $msvmKvpExchangeDataItem.PSBase.GetText(1))
    $job = [wmi]$result.Job

    while($job.jobstate -lt 7) {
        $job.get()
    }
    LogMsg $job.ErrorCode
    LogMsg $job.Status

    # Due to a change in behavior between Windows Server versions, we need to modify
    # acceptance criteria based on the version of the HyperVisor.
    [System.Int32]$buildNR = $osInfo.BuildNumber
    if ($buildNR -ge 9600) {
        if ($job.ErrorCode -eq 0) {
            LogMsg "Info : Windows Server returns success even when the KVP item does not exist"
            return "PASS"
        }
        LogErr "Error: RemoveKVPItems() returned error code $($job.ErrorCode)"
        return "FAIL"
    } elseIf ($buildNR -ge 9200) {
        if ($job.ErrorCode -eq 32773) {
            LogMsg "Info : RemoveKvpItems() correctly returned 32773"
            return "PASS"
        }
        LogErr "Error: RemoveKVPItems() returned error code $($job.ErrorCode) rather than 32773"
        return "FAIL"
    } else {
        LogErr "Error: Unsupported build of Windows Server"
        return "FAIL"
    }
}

Main -VMName $AllVMData.RoleName -HvServer $xmlConfig.config.Hyperv.Host.ServerName `
        -RootDir $WorkingDirectory -TestParams $TestParams