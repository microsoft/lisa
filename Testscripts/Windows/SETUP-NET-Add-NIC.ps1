# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Description
    This setup script adds a NIC to VM
    The testParams have the format of:
        NIC=NIC type, Network Type, Network Name, MAC Address

    NIC Type can be one of the following:
        NetworkAdapter
        LegacyNetworkAdapter

    Network Type can be one of the following:
        External
        Internal
        Private
        None

    Network Name is the name of a existing network. If Network Type is set to None however, the NIC is not connected to any switch.
    This script will make sure the network switch exists before adding the NIC (test is disabled in case of None switch type).

    The following is an example of a testParam for adding a NIC
        "NIC=NetworkAdapter,Internal,InternalNet,001600112200"
#>

param([String] $TestParams)

function Main {
    param (
        $VMName,
        $HvServer,
        $TestParams
    )
    $currentDir= "$pwd\"
    $testfile = "macAddress.file"
    $pathToFile="$currentDir"+"$testfile"
    $streamWrite = [System.IO.StreamWriter] $pathToFile
    $macAddress = $null

    $params = $TestParams.Split(';')
    foreach ($p in $params) {
        $temp = $p.Trim().Split('=')
        if ($temp.Length -ne 2) {
            continue
        }
        if ($temp[0].Trim() -match "NIC_") {
            $nicArgs = $temp[1].Split(',')
            if ($nicArgs.Length -lt 3) {
                LogErr "Error: Incorrect number of arguments for NIC test parameter: $p"
                return $false

            }
            $nicType = $nicArgs[0].Trim()
            $networkType = $nicArgs[1].Trim()
            $networkName = $nicArgs[2].Trim()
            if ($nicArgs.Length -eq 4) {
                $macAddress = $nicArgs[3].Trim()
            }
            $legacy = $false

            # Validate the network adapter type
            if (@("NetworkAdapter", "LegacyNetworkAdapter") -notcontains $nicType) {
                LogErr "Error: Invalid NIC type: $nicType"
                LogErr "       Must be either 'NetworkAdapter' or 'LegacyNetworkAdapter'"
                return $false
            }

            if ($nicType -eq "LegacyNetworkAdapter") {
                $legacy = $true
                $vmGeneration = Get-VMGeneration $VMName $HvServer
                if ($vmGeneration -eq 2 ) {
                    LogWarn "Warning: Generation 2 VM does not support LegacyNetworkAdapter, please skip this case in the test script"
                    return $True
                }
            }

            # Validate the Network type
            if (@("External", "Internal", "Private", "None") -notcontains $networkType) {
                LogErr "Error: Invalid netowrk type: $networkType"
                LogErr "       Network type must be either: External, Internal, Private, None"
                return $false
            }

            # Make sure the network exists
            if ($networkType -notlike "None") {
                $vmSwitch = Get-VMSwitch -Name $networkName -ComputerName $HvServer
                if (-not $vmSwitch) {
                    LogErr "Error: Invalid network name: $networkName"
                    LogErr "       The network does not exist"
                    return $false
                }

                # Make sure network is of stated type
                if ($vmSwitch.SwitchType -notlike $networkType) {
                    LogErr "Error: Switch $networkName is type $vmSwitch.SwitchType (not $networkType)"
                    return $false
                }
            }

            $macAddress = Get-RandUnusedMAC $HvServer
            LogMsg "Info: Generated MAC address: $macAddress"
            $streamWrite.WriteLine($macAddress)

            # Add NIC with given MAC Address
            if ($networkType -notlike "None") {
                Add-VMNetworkAdapter -VMName $VMName -SwitchName $networkName -StaticMacAddress $macAddress -IsLegacy:$legacy -ComputerName $HvServer
            } else {
                Add-VMNetworkAdapter -VMName $VMName -StaticMacAddress $macAddress -IsLegacy:$legacy -ComputerName $HvServer
            }

            if ($? -ne "True") {
                LogErr "Error: Add-VMNetworkAdapter failed"
                $retVal = $False
            } else {
                if ($networkName -like '*SRIOV*') {
                    $(get-vm -name $VMName -ComputerName $HvServer).NetworkAdapters | Where-Object { $_.SwitchName -like 'SRIOV' } | Set-VMNetworkAdapter -IovWeight 1
                    if ($? -ne $True) {
                        LogErr "Error: Unable to enable SRIOV"
                        $retVal = $False
                    } else {
                        $retVal = $True
                    }
                } else {
                    $retVal = $True
                }
            }
        }
    }
    $streamWrite.close()
    return $retVal
}

Main -VMName $AllVMData.RoleName -hvServer $xmlConfig.config.Hyperv.Host.ServerName `
         -TestParams $TestParams