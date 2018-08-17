# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Synopsis
    Verify the basic SQM read operations work.
.Description
    Ensure the Data Exchange service is enabled for the VM and then
    verify if basic SQM data can be retrieved from vm.
    For SQM data to be retrieved, kvp process needs to be stopped on vm
#>

param([string] $TestParams)

function Stop-KVP {
    param (
        [String] $VMIpv4,
        [String] $VMSSHPort,
        [String] $VMUser,
        [String] $VMPassword,
        [String] $RootDir
    )
    
    $cmdToVM = @"
#!/bin/bash
    ps aux | grep kvp
    if [ `$? -ne 0 ]; then
      echo "KVP is already disabled" >> /root/StopKVP.log 2>&1
      exit 0
    fi

    kvpPID=`$(ps aux | grep kvp | awk 'NR==1{print `$2}')
    if [ `$? -ne 0 ]; then
        echo "Could not get PID of KVP" >> /root/StopKVP.log 2>&1
        exit 0
    fi

    kill `$kvpPID
    if [ `$? -ne 0 ]; then
        echo "Could not stop KVP process" >> /root/StopKVP.log 2>&1
        exit 0
    fi

    echo "KVP process stopped successfully"
    exit 0
"@
    $FILE_NAME = "StopKVP.sh"

    # check for file
    if (Test-Path ".\${FILE_NAME}") {
        Remove-Item ".\${FILE_NAME}"
    }

    Add-Content $FILE_NAME "$cmdToVM"

    # send file
    RemoteCopy -uploadTo $VMIpv4 -port $VMSSHPort -files $FILE_NAME `
        -username "root" -password $VMPassword -upload

    $retVal = RunLinuxCmd -username "root" -password $VMPassword -ip $VMIpv4 -port $VMSSHPort `
        -command "cd /root && chmod u+x ${FILE_NAME} && sed -i 's/\r//g' ${FILE_NAME} && ./${FILE_NAME}"

    return $retVal
}

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
    
    $intrinsic = $True
    
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

    # Get host build number
    $buildNumber = Get-HostBuildNumber $HvServer
    if ($buildNumber -eq 0) {
        LogErr "Error: Wrong Windows build number"
        return "Aborted"
    }

    # Verify the Data Exchange Service is enabled for this VM
    $des = Get-VMIntegrationService -VMName $VMName -ComputerName $HvServer
    if (-not $des) {
        LogErr "Error: Data Exchange Service is not enabled for this VM"
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

    # Disable KVP on vm
    $retVal = Stop-KVP -vmIpv4 $Ipv4 -VMSSHPort $VMPort -VMUser $VMUserName `
        -VMPassword $VMPassword -RootDir $RootDir
    if (-not $retVal) {
        LogErr "Failed to stop KVP process on VM"
        return "FAIL"
    }

    # Create a data exchange object and collect KVP data from the VM
    $vm = Get-WmiObject -ComputerName $HvServer -Namespace root\virtualization\v2 `
            -Query "Select * From Msvm_ComputerSystem Where ElementName=`'$VMName`'"
    if (-not $vm) {
        LogErr"Error: Unable to the VM '${VMName}' on the local host"
        return "FAIL"
    }

    $kvp = Get-WmiObject -ComputerName $HvServer -Namespace root\virtualization\v2 `
            -Query "Associators of {$vm} Where AssocClass=Msvm_SystemDevice ResultClass=Msvm_KvpExchangeComponent"
    if (-not $kvp) {
        LogErr "Error: Unable to retrieve KVP Exchange object for VM '${VMName}'"
        return "FAIL"
    }

    if ($intrinsic) {
        LogMsg "Intrinsic Data"
        $kvpData = $kvp.GuestIntrinsicExchangeItems
    } else {
        LogMsg "Non-Intrinsic Data"
        $kvpData = $kvp.GuestExchangeItems
    }
    
    #after disable KVP on vm, $kvpData is empty on hyper-v 2012 host
    if (-not $kvpData -and $buildNumber -lt 9600 ) {
        return "FAIL"
    }

    $dict = Convert-KvpToDict $kvpData
    
    # Write out the kvp data so it appears in the log file
    foreach ($key in $dict.Keys) {
        $value = $dict[$key]
        LogMsg ("  {0,-27} : {1}" -f $key, $value)
    }

    if ($intrinsic) {
        # Create an array of key names specific to a build of Windows.
        $osSpecificKeyNames = $null

        if ($buildNumber -ge 9600) {
            $osSpecificKeyNames = @("OSDistributionName", "OSDistributionData", 
                                    "OSPlatformId","OSKernelVersion")
        } else {
            $osSpecificKeyNames = @("OSBuildNumber", "ServicePackMajor", "OSVendor", 
                                    "OSMajorVersion", "OSMinorVersion", "OSSignature")
        }
        foreach ($key in $osSpecificKeyNames) {
            if (-not $dict.ContainsKey($key)) {
                LogErr "Error: The key '${key}' does not exist"
                return "FAIL"
            }
        }
    } else {
        if ($dict.length -gt 0) {
            LogMsg "Info: $($dict.length) non-intrinsic KVP items found"
            return "FAIL"
        } else {
            LogErr "Error: No non-intrinsic KVP items found"
            return "FAIL"
        }
    }

    return "PASS"
}

Main -VMName $AllVMData.RoleName -HvServer $xmlConfig.config.Hyperv.Host.ServerName `
         -Ipv4 $AllVMData.PublicIP -VMPort $AllVMData.SSHPort `
         -VMUserName $user -VMPassword $password -RootDir $WorkingDirectory `
         -TestParams $TestParams
