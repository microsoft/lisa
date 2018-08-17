# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Synopsis
    Modify an existing KVP item.

.Description
    Modifie an existing KVP item on a Linux VM.  The operation
    is performed on the host side.
#>



############################################################################
#
# Main script body
#
############################################################################

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
    $tcCovered = "unknown"
    
    if (-not $TestParams) {
        LogErr "Error: No TestParams provided"
        LogErr "       This script requires the Key & value test parameters"
        return "Aborted"
    }
    if (-not $RootDir) {
        LogErr "Warn : no RootDir test parameter was supplied"
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

    if (-not $key) {
        LogErr "Error: Missing testParam Key to be added"
        return "FAIL"
    }
    if (-not $value) {
        LogErr "Error: Missing testParam Value to be added"
        return "FAIL"
    }

    # Modify the Key Value pair from the Pool 0 on guest OS. If the Key is already not present, will return proper message.
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

    LogMsg "Info : Modifying Key '${key}'to '${Value}'"

    $msvmKvpExchangeDataItem.Source = 0
    $msvmKvpExchangeDataItem.Name = $Key
    $msvmKvpExchangeDataItem.Data = $Value
    $result = $vmManagementService.ModifyKvpItems($vmGuest, $msvmKvpExchangeDataItem.PSBase.GetText(1))
    $job = [wmi]$result.Job

    # Check if the modify worked
    while($job.jobstate -lt 7) {
        $job.get()
    }

    if ($job.ErrorCode -ne 0) {
        LogErr "Error: while modifying the key value pair"
        LogErr "Error: Job error code = $($Job.ErrorCode)"

        if ($job.ErrorCode -eq 32773) {  
            LogErr "Error: Key does not exist.  Key = '${key}'"
            return "FAIL"
        } else {
            LogErr "Error: Unable to modify key"
            return "FAIL"
        }
    }

    if ($job.Status -ne "OK") {
        LogErr "Error: KVP modify job did not complete with status OK"
        return "FAIL"
    }

    LogMsg "Info : KVP item successfully modified"

    return "PASS"
}

Main -VMName $AllVMData.RoleName -HvServer $xmlConfig.config.Hyperv.Host.ServerName `
        -RootDir $WorkingDirectory -TestParams $TestParams