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

param(
    [String] $TestParams,
    [object] $AllVMData
)

function Main {
    param (
        $VMName,
        $HvServer,
        $TestParams
    )
    $isDynamicMAC = $false

    $params = $TestParams.Split(';')
    foreach ($p in $params) {
        $temp = $p.Trim().Split('=')
        if ($temp[0].Trim() -match "NIC_") {
            $nicArgs = $temp[1].Split(',')
            if ($nicArgs.Length -eq 3) {
                $isDynamicMAC = $true
            }
        }
    }

    if ($isDynamicMAC -eq $true) {
        $currentDir= "$pwd\"
        $testfile = "macAddress.file"
        $pathToFile="$currentDir"+"$testfile"
        $streamWrite = [System.IO.StreamWriter] $pathToFile
        $macAddress = $null
    }

    foreach ($p in $params) {
        $temp = $p.Trim().Split('=')
        if ($temp.Length -ne 2) {
            continue
        }
        if ($temp[0].Trim() -match "NIC_") {
            $nicArgs = $temp[1].Split(',')
            if ($nicArgs.Length -lt 3) {
                Write-LogErr "Incorrect number of arguments for NIC test parameter: $p"
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
                Write-LogErr "Invalid NIC type: $nicType"
                Write-LogErr "       Must be either 'NetworkAdapter' or 'LegacyNetworkAdapter'"
                return $false
            }

            if ($nicType -eq "LegacyNetworkAdapter") {
                $legacy = $true
                $vmGeneration = Get-VMGeneration $VMName $HvServer
                if ($vmGeneration -eq 2 ) {
                    Write-LogWarn "Generation 2 VM does not support LegacyNetworkAdapter, please skip this case in the test script"
                    return $True
                }
            }

            # Validate the Network type
            if (@("External", "Internal", "Private", "None") -notcontains $networkType) {
                Write-LogErr "Invalid netowrk type: $networkType"
                Write-LogErr "       Network type must be either: External, Internal, Private, None"
                return $false
            }

            # Make sure the network exists
            if ($networkType -notlike "None") {
                $vmSwitch = Get-VMSwitch -Name $networkName -ComputerName $HvServer
                if (-not $vmSwitch) {
                    Write-LogErr "Invalid network name: $networkName"
                    Write-LogErr "       The network does not exist"
                    return $false
                }

                # Make sure network is of stated type
                if ($vmSwitch.SwitchType -notlike $networkType) {
                    Write-LogErr "Switch $networkName is type $vmSwitch.SwitchType (not $networkType)"
                    return $false
                }
            }

            if ($isDynamicMAC -eq $true) {
                $macAddress = Get-RandUnusedMAC $HvServer
                Write-LogInfo "Generated MAC address: $macAddress"
                $streamWrite.WriteLine($macAddress)
            } else {
                # Validate the MAC is the correct length
                if ($macAddress.Length -ne 12) {
                    Write-LogErr "Invalid mac address: $p"
                    return $false
                }
                # Make sure each character is a hex digit
                $ca = $macAddress.ToCharArray()
                foreach ($c in $ca) {
                    if ($c -notmatch "[A-Fa-f0-9]") {
                        Write-LogErr "MAC address contains non hexidecimal characters: $c"
                        return $false
                    }
                }
            }

            # Add NIC with given MAC Address
            if ($networkType -notlike "None") {
                Add-VMNetworkAdapter -VMName $VMName -SwitchName $networkName -StaticMacAddress $macAddress -IsLegacy:$legacy -ComputerName $HvServer
            } else {
                Add-VMNetworkAdapter -VMName $VMName -StaticMacAddress $macAddress -IsLegacy:$legacy -ComputerName $HvServer
            }
            if ($? -ne "True") {
                Write-LogErr "Add-VMNetworkAdapter failed"
                $retVal = $False
            } else {
                if ($networkName -like '*SRIOV*') {
                    $(Get-VM -Name $VMName -ComputerName $HvServer).NetworkAdapters | Where-Object { $_.SwitchName -like '*SRIOV*' } | Set-VMNetworkAdapter -IovWeight 1
                    if ($? -ne $True) {
                        Write-LogErr "Unable to enable SRIOV"
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
    if ($isDynamicMAC -eq $true){
        $streamWrite.close()
    }
    return $retVal
}

Main -VMName $AllVMData.RoleName -hvServer $GlobalConfig.Global.Hyperv.Hosts.ChildNodes[0].ServerName `
         -TestParams $TestParams
