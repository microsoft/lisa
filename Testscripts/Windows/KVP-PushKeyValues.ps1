# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Synopsis
    Linux VM creates a KVP item, then verify from the host.

.Description
    A Linux VM will create a non-intrinsic KVP item.  Then
    verify the host can see the KVP item.
#>

param([String] $TestParams)

function Main {
    param (
        $VMName,
        $HvServer,
        $Ipv4,
        $VMPort,
        $VMUserName,
        $VMPassword,
        $RootDir,
        $TestParams
    )

    $key = $null
    $value = $null
    $tcCovered = $null

    if (-not $RootDir) {
        LogErr "Warn : no RootDir was specified"
    }
    else {
        Set-Location $RootDir
    }
    if (-not $TestParams) {
        LogErr "Error: No test parameters specified"
        return "Aborted"
    }

    # For loggine purposes, display the TestParams
    LogErr "Info: TestParams : '${TestParams}'"

    # Parse the test parameters
    $params = $TestParams.Split(";")
    foreach ($p in $params) {
        $fields = $p.Split("=")
        if ($fields.count -ne 2) {
            continue
        }
        $rValue = $fields[1].Trim()
        switch ($fields[0].Trim()) {      
            "key"        { $key       = $rValue }
            "value"      { $value     = $rValue }
            "TC_COVERED" { $tcCovered = $rValue }
            default      {}       
        }
    }

    # Ensure all required test parameters were provided
    if (-not $key) {
        "Error: The 'key' test parameter was not provided"
        return "FAIL"
    }
    if (-not $value) {
        "Error: The 'value' test parameter was not provided"
        return "FAIL"
    }
    if (-not $tcCovered) {
        LogErr "Warn : the TC_COVERED test parameter was not provided"
    }

    # Verify the Data Exchange Service is enabled for the test VM
    LogMsg "Info: Creating Integrated Service object"
    $des = Get-VMIntegrationService -VMName $VMName -ComputerName $HvServer
    if (-not $des) {
        LogErr "Error: Unable to retrieve Integration Service status from VM '${VMName}'"
        return "FAIL"
    }
    foreach ($svc in $des) {
        if ($svc.Name -eq "Key-Value Pair Exchange") {
            if (-not $svc.Enabled) {
                LogErr "Error: The Data Exchange Service is not enabled for VM '${VMName}'"
                return "FAIL"
            }
            break
        }
    }

    # The kvp_client file should be listed in the <files> tab of
    # the test case definition, which tells the stateEngine to
    # copy the file to the test VM.  Set the x bit on the kvp_client
    # image, then run kvp_client to add a non-intrinsic kvp item 
    LogMsg "Info: Trying to detect OS architecture"
    $kvpClient = $null
    $retVal = RunLinuxCmd -username "root" -password $VMPassword -ip $Ipv4 -port $VMPort `
                -command "uname -a | grep x86_64"
    if (-not $retVal) {
        $retVal = RunLinuxCmd -username "root" -password $VMPassword -ip $Ipv4 -port $VMPort `
                    -command "uname -a | grep i686"
        if (-not ($retVal)) {
            LogErr "Error: Could not determine OS architecture"
            return "FAIL"
        } else {
            LogMsg "Info: 32 bit architecture detected"
            $kvpClient = "kvp_client32"
        }
    } else {
        LogMsg "Info: 64 bit architecture detected"
        $kvpClient = "kvp_client64"
    }  

    LogMsg "Info: chmod 755 $kvpClient"
    $retVal = RunLinuxCmd -username $VMUserName -password $VMPassword -ip $Ipv4 -port $VMPort `
                -command "chmod 755 ./${kvpClient}" -runAsSudo

    LogMsg "Info: $kvp_client append 1 ${key} ${value}"
    $retVal = RunLinuxCmd -username $VMUserName -password $VMPassword -ip $Ipv4 -port $VMPort `
                -command "./${kvpClient} append 1 ${key} ${value}" -runAsSudo

    # Create a data exchange object and collect non-intrinsic KVP data from the VM
    LogMsg "Info: Collecting nonintrinsic KVP data from guest"
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
    $kvpData = $kvp.GuestExchangeItems
    if (-not $kvpData) {
        LogErr "Error: KVP NonIntrinsic data is null"
        return "FAIL"
    }
    $dict = Convert-KvpToDict $kvpData

    # For logging purposed, display all kvp data
    LogMsg "Info: Non-Intrinsic data"
    foreach ($key in $dict.Keys) {
        $value = $dict[$key]
        LogMsg ("       {0,-27} : {1}" -f $key, $value)
    }

    # Check to make sure the guest created KVP item is returned
    if (-not $dict.ContainsKey($key)) {
        LogErr "Error: The key '${key}' does not exist in the non-intrinsic data"
        return "FAIL"
    }
    $data = $dict[$key]
    if ( $data -ne $value) {
        LogErr "Error: The KVP item has an incorrect value:  ${key} = ${value}"
        return "FAIL"
    }

    # If we made it here, everything worked
    return "PASS"
}

Main -VMName $AllVMData.RoleName -HvServer $xmlConfig.config.Hyperv.Host.ServerName `
         -Ipv4 $AllVMData.PublicIP -VMPort $AllVMData.SSHPort `
         -VMUserName $user -VMPassword $password -RootDir $WorkingDirectory `
         -TestParams $TestParams