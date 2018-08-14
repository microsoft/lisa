# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Synopsis
    Verify the basic KVP read operations work.

.Description
    Ensure the Data Exchange service is enabled for the VM and then
    verify basic KVP read operations can be performed by reading
    intrinsic data from the VM.  Additionally, check that three
    keys are part of the returned data.
#>

param([String] $TestParams)

function Main {
    param (
        $VMName,
        $HvServer,
        $RootDir,
        $TestParams
    )
    
    $intrinsic = $True
    
    if (-not $RootDir) {
        LogErr "Warn : no RootDir was specified"
    } else {
        Set-Location $RootDir
    }

    # Debug - display the test parameters so they are captured in the log file
    LogMsg "TestParams : '${TestParams}'"

    # Parse the test parameters
    $params = $TestParams.Split(";")
    foreach ($p in $params) {
        $fields = $p.Split("=")
        switch ($fields[0].Trim()) {      
            "nonintrinsic" { $intrinsic = $False }
            "TC_COVERED"   { $tcCovered = $fields[1].Trim() }
            default  {}       
        }
    }
    LogMsg "Covers: ${tcCovered}"
    
    # Verify the Data Exchange Service is enabled for this VM
    $des = Get-VMIntegrationService -VMName $VMName -ComputerName $HvServer
    if (-not $des) {
        LogErr "Error: Unable to retrieve Integration Service status from VM '${VMName}'"
        return "FAIL"
    }

    $serviceEnabled = $False
    foreach ($svc in $des) {
        if ($svc.Name -eq "Key-Value Pair Exchange") {
            $serviceEnabled = $svc.Enabled
            break
        }
    }

    if (-not $serviceEnabled) {
        LogErr "Error: The Data Exchange Service is not enabled for VM '${VMName}'"
        return "FAIL"
    }

    # Create a data exchange object and collect KVP data from the VM
    $vm = Get-WmiObject -ComputerName $HvServer -Namespace root\virtualization\v2 `
        -Query "Select * From Msvm_ComputerSystem Where ElementName=`'$VMName`'"
    if (-not $vm) {
        LogErr "Error: Unable to the VM '${VMName}' on the local host"
        return "FAIL"
    }

    $kvp = Get-WmiObject -ComputerName $HvServer -Namespace root\virtualization\v2 `
        -Query "Associators of {$vm} Where AssocClass=Msvm_SystemDevice ResultClass=Msvm_KvpExchangeComponent"
    if (-not $kvp) {
        LogErr "Error: Unable to retrieve KVP Exchange object for VM '${VMName}'"
        return "FAIL"
    }
    
    if ($Intrinsic) {
        LogMsg "Intrinsic Data"
        $kvpData = $kvp.GuestIntrinsicExchangeItems
    } else {
        LogMsg "Non-Intrinsic Data"
        $kvpData = $kvp.GuestExchangeItems
    }
    $dict = Convert-KvpToDict $kvpData
    
    # Write out the kvp data so it appears in the log file
    foreach ($key in $dict.Keys) {
        $value = $dict[$key]
        LogMsg ("  {0,-27} : {1}" -f $key, $value)
    }

    if ($Intrinsic) {
        #Create an array of key names
        $keyName = @("OSVersion", "OSName", "ProcessorArchitecture",
            "IntegrationServicesVersion", "FullyQualifiedDomainName", "NetworkAddressIPv4",
            "NetworkAddressIPv6")
        $testPassed = $True
        foreach ($key in $keyName) {
            if (-not $dict.ContainsKey($key)) {
                LogErr "Error: The key '${key}' does not exist"
                $testPassed = $False
                break
            }
        }
    } else {
        if ($dict.length -gt 0) {
            LogMsg "Info: $($dict.length) non-intrinsic KVP items found"
            $testPassed = $True
        } else {
            LogErr "Error: No non-intrinsic KVP items found"
            $testPassed = $False
        }
    }
    if ($testPassed) {
        $result = "PASS"
    } else {
        $result = "FAIL"
    }
    
    return $result
}

Main -VMName $AllVMData.RoleName -HvServer $xmlConfig.config.Hyperv.Host.ServerName `
        -RootDir $WorkingDirectory -TestParams $TestParams