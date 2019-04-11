# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Synopsis
    Switch an existing NIC (with a certain MAC address) to a different network.
#>

param([string] $TestParams,
    [object] $AllVMData,
    [string] $VMName)

function Main {
    param (
        $VMName,
        $HvServer,
        $TestParams
    )
    $retVal = $null
    $CurrentDir= "$pwd\"
    $testfile = "macAddress.file"
    $pathToFile="$CurrentDir"+"$testfile"
    $streamReader = [System.IO.StreamReader] $pathToFile
    $macAddress = $null

    # Parse the testParams string, then process each parameter
    $params = $testParams.Split(';')
    foreach ($p in $params) {
        $temp = $p.Trim().Split('=')
        if ($temp.Length -ne 2) {
            continue
        }

        # Is this a SWITCH=* parameter
        if ($temp[0].Trim() -eq "SWITCH") {
            $nicArgs = $temp[1].Split(',')
            if ($nicArgs.Length -lt 3) {
                Write-LogErr "Error: Incorrect number of arguments for SWITCH test parameter: $p"
                return $False
            }

            $nicType = $nicArgs[0].Trim()
            $networkType = $nicArgs[1].Trim()
            $networkName = $nicArgs[2].Trim()
            if ($nicArgs.Length -eq 4) {
                $macAddress = $nicArgs[3].Trim()
            } else {
                $macAddress = $streamReader.ReadLine()
            }
            $legacy = $False

            # Validate the network adapter type
            if (@("NetworkAdapter", "LegacyNetworkAdapter") -notcontains $nicType) {
                Write-LogErr "Error: Invalid NIC type: $nicType"
                Write-LogErr "Must be either 'NetworkAdapter' or 'LegacyNetworkAdapter'"
                return $False
            }

            if ($nicType -eq "LegacyNetworkAdapter") {
                $legacy = $true
            }

            # Validate the Network type
            if (@("External", "Internal", "Private", "None") -notcontains $networkType) {
                Write-LogErr "Error: Invalid netowrk type: $networkType"
                Write-LogErr "Network type must be either: External, Internal, Private, None"
                return $False
            }

            # Make sure the network exists
            if ($networkType -notlike "None") {
                $vmSwitch = Get-VMSwitch -Name $networkName -ComputerName $hvServer
                if (-not $vmSwitch) {
                    Write-LogErr "Error: Invalid network name: $networkName"
                    Write-LogErr "The network does not exist"
                    return $False
                }
            }

            # Get NIC with given MAC Address
            $nic = Get-VMNetworkAdapter -VMName $VMName -ComputerName $hvServer -IsLegacy:$legacy | where {$_.MacAddress -eq $macAddress }
            if ($nic) {
                if ($networkType -like "None") {
                    Disconnect-VMNetworkAdapter $nic
                } else {
                    Connect-VMNetworkAdapter -VMNetworkAdapter $nic -SwitchName $networkName -Confirm:$False
                }

                $retVal = $?
            } else {
                Write-LogErr "Error: $VMName - No NIC found with MAC $macAddress ."
            }
        }
    }

    $streamReader.close()
    return $retVal
}

if (-not $VMName) {
    $VMName = $AllVMData.RoleName
}
Main -VMName $VMName -hvServer $GlobalConfig.Global.Hyperv.Hosts.ChildNodes[0].ServerName `
         -TestParams $TestParams
