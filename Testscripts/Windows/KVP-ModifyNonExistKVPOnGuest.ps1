# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Synopsis
    Modify Non-Existing KVP item.

.Description
    Modify Non-Existing KVP item on a Linux VM.  The operation
    is performed on the host side.
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

    # Find the TestParams we require
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

    # Modify the Non-Existing Key Value pair from the Pool 0 on guest OS. If the Key is already present, will return proper message.
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

    $msvmKvpExchangeDataItemPath = "\\$HvServer\root\virtualization\v2:Msvm_KvpExchangeDataItem"
    $msvmKvpExchangeDataItem = ([WmiClass]$msvmKvpExchangeDataItemPath).CreateInstance()
    if (-not $msvmKvpExchangeDataItem) {
        Write-LogErr "Error: Unable to create Msvm_KvpExchangeDataItem object"
        return "FAIL"
    }

    Write-LogInfo "Info : Detecting Host version of Windows Server"
    $osInfo = GWMI Win32_OperatingSystem -ComputerName $HvServer
    if (-not $osInfo) {
        Write-LogErr "Error: Unable to collect Operating System information"
        return "FAIL"
    }
    [System.Int32]$buildNR = $osInfo.BuildNumber

    Write-LogInfo "Info : Modifying Key '${key}'to '${Value}'"

    $msvmKvpExchangeDataItem.Source = 0
    $msvmKvpExchangeDataItem.Name = $key
    $msvmKvpExchangeDataItem.Data = $value
    $result = $vmManagementService.ModifyKvpItems($vmGuest, $msvmKvpExchangeDataItem.PSBase.GetText(1))
    $job = [wmi]$result.Job

    # Check if the modify worked
    while($job.jobstate -lt 7) {
        $job.get()
    }

    if ($job.ErrorCode -ne 0) {
        Write-LogErr "Error: while modifying the key value pair"
        Write-LogErr "Error: Job error code = $($Job.ErrorCode)"

        if ($job.ErrorCode -eq 32773) {
            Write-LogErr "Error (as expected): Key = '${key} ,Non-existing key cannot be modified Error Code-' $($Job.ErrorCode) "
            return "PASS"
        } elseIf ($job.ErrorCode -eq 32779 -And $buildNR -ge 10000) {
            Write-LogErr "Error (as expected): Key = '${key} ,Non-existing key cannot be modified Error Code-' $($Job.ErrorCode) "
            return "PASS"
        } else {
            Write-LogErr "Error: Unable to modify key"
            return "FAIL"
        }
    }

    if ($job.Status -eq "OK") {
        "Error: Non-existing KVP modified with status OK, Check Key and Value pair exist or not in pool 0"
        return "FAIL"
    }
}

Main -VMName $AllVMData.RoleName -HvServer $xmlConfig.config.Hyperv.Hosts.ChildNodes[0].ServerName `
        -RootDir $WorkingDirectory -TestParams $TestParams
