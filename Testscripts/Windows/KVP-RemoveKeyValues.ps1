# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Synopsis
    Delete a KVP item from a Linux guest.
.Description
    Delete a KVP item from pool 0 on a Linux guest.
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
        Write-LogErr "       This script requires the Key & value test parameters"
        return "Aborted"
    }
    if (-not $RootDir) {
        Write-LogErr "Warn : no RootDir test parameter was supplied"
    } else {
        Set-Location $RootDir
    }

    $params = $TestParams.Split(";")
    foreach ($p in $params) {
        $fields = $p.Split("=")

        switch ($fields[0].Trim()) {
            "key"        { $key       = $fields[1].Trim() }
            "value"      { $value     = $fields[1].Trim() }
            default   {}  # unknown param - just ignore it
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

    # Delete the Key Value pair from the Pool 0 on guest OS. If the Key is already not present, will return proper message.
    Write-LogInfo "Info : Creating VM Management Service object"
    $vmManagementService = Get-WmiObject -ComputerName $HvServer -class "Msvm_VirtualSystemManagementService" `
                                -namespace "root\virtualization\v2"
    if (-not $vmManagementService) {
        Write-LogErr "Error: Unable to create a VMManagementService object"
        return "FAIL"
    }

    $vmGuest = Get-WmiObject -ComputerName $HvServer -Namespace root\virtualization\v2 `
                    -Query "Select * From Msvm_ComputerSystem Where ElementName='$VMName'"
    if (-not $vmGuest) {
        Write-LogErr "Error: Unable to create VMGuest object"
        return "FAIL"
    }

    Write-LogInfo "Info : Creating Msvm_KvpExchangeDataItem object"
    $msvmKvpExchangeDataItemPath = "\\$HvServer\root\virtualization\v2:Msvm_KvpExchangeDataItem"
    $msvmKvpExchangeDataItem = ([WmiClass]$msvmKvpExchangeDataItemPath).CreateInstance()
    if (-not $msvmKvpExchangeDataItem) {
        Write-LogErr "Error: Unable to create Msvm_KvpExchangeDataItem object"
        return "FAIL"
    }

    Write-LogInfo "Info : Deleting Key '${key}' from Pool 0"
    $msvmKvpExchangeDataItem.Source = 0
    $msvmKvpExchangeDataItem.Name = $key
    $msvmKvpExchangeDataItem.Data = $value
    $result = $vmManagementService.RemoveKvpItems($vmGuest, $msvmKvpExchangeDataItem.PSBase.GetText(1))
    $job = [wmi]$result.Job
    while($job.jobstate -lt 7) {
        $job.get()
    }
    if ($job.ErrorCode -ne 0) {
        Write-LogErr "Error: Deleting the key value pair"
        Write-LogErr "Error: Job error code = $($Job.ErrorCode)"

        if ($job.ErrorCode -eq 32773) {
            Write-LogErr "Error: Key does not exist.  Key = '${key}'"
            return "FAIL"
        } else {
            Write-LogErr "Error: Unable to delete KVP key '${key}'"
            return "FAIL"
        }
    }
    if ($job.Status -ne "OK") {
        Write-LogErr "Error: KVP delete job did not complete with status OK"
        return "FAIL"
    }

    # If we made it here, everything worked
    Write-LogInfo "Info : KVP item successfully deleted"
    return "PASS"
}

Main -VMName $AllVMData.RoleName -HvServer $xmlConfig.config.Hyperv.Hosts.ChildNodes[0].ServerName `
        -RootDir $WorkingDirectory -TestParams $TestParams
