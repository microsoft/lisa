# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

#####################################################################

<#
.Synopsis
 Run the StartVM test.

 Description:
    This script sets up additional Network Adapters for a second (dependency) VM,
    starts it first and configures the interface files in the OS.
    Afterwards the main test is started together with the main VM.
#>

param([string] $TestParams)

function Main {
    param (
        $VMName,
        $HvServer,
        $VMPort,
        $VMUserName,
        $VMPassword,
        $TestParams
    )
    $vm2StaticIP = $null
    $netmask = $null
    $bootproto = $null
    $checkpointName = $null
    $guestUsername = "root"

    $params = $TestParams.Split(';')
    foreach ($p in $params) {
        $fields = $p.Split("=")
        switch ($fields[0].Trim()) {
            "VM2Name" { $VM2Name = $fields[1].Trim() }
            "STATIC_IP2" { $vm2StaticIP = $fields[1].Trim() }
            "NETMASK" { $netmask = $fields[1].Trim() }
            "VM_VLAN_ID" { $vlanId = $fields[1].Trim() }
            "CheckpointName" { $checkpointName = $fields[1].Trim() }
            "NIC_1" {
                $nicArgs = $fields[1].Split(',')
                if ($nicArgs.Length -lt 3) {
                    Write-LogErr "Incorrect number of arguments for NIC test parameter: $p"
                    return $False
                }

                $nicType = $nicArgs[0].Trim()
                $networkType = $nicArgs[1].Trim()
                $networkName = $nicArgs[2].Trim()

                # Validate the network adapter type
                if ("NetworkAdapter" -notcontains $nicType) {
                    Write-LogErr "Invalid NIC type: $nicType . Must be 'NetworkAdapter'"
                    return $False
                }

                # Validate the Network type
                if (@("External", "Internal", "Private") -notcontains $networkType) {
                    Write-LogErr "Invalid netowrk type: $networkType .  Network type must be either: External, Internal, Private"
                    return $False
                }

                # Make sure the network exists
                $vmSwitch = Get-VMSwitch -Name $networkName -ComputerName $HvServer
                if (-not $vmSwitch) {
                    Write-LogErr "Invalid network name: $networkName . The network does not exist."
                    return $False
                }
            }
            default {}
        }
    }

    if (-not $VM2Name) {
        Write-LogErr "Test parameter VM2Name was not specified"
        return $False
    }

    if (-not $netmask) {
        $netmask = 255.255.255.0
    }

    if (-not $vm2StaticIP) {
        $bootproto = "dhcp"
    } else {
        $bootproto = "static"
    }

    # Verify the VMs exists
    $vm2 = Get-VM -Name $VM2Name -ComputerName $HvServer -ErrorAction SilentlyContinue
    if (-not $vm2) {
        Write-LogErr "VM ${VM2Name} does not exist"
        return $False
    }

    # Generate a Mac address for the VM's test NIC
    $vm2MacAddress = Get-RandUnusedMAC $HvServer
    $currentDir= "$pwd\"
    $testfile = "macAddressDependency.file"
    $pathToFile="$currentDir"+"$testfile"
    $streamWrite = [System.IO.StreamWriter] $pathToFile
    $streamWrite.WriteLine($vm2MacAddress)
    $streamWrite.close()

    # Construct SETUP-NET-Add-NIC Parameter
    $vm2NicAddParam = "NIC_1=NetworkAdapter,$networkType,$networkName,$vm2MacAddress"
    Write-LogInfo $vm2NicAddParam
    if (Test-Path ".\Testscripts\Windows\SETUP-NET-Add-NIC.ps1") {
        # Make sure VM2 is shutdown
        if (Get-VM -Name $VM2Name -ComputerName $HvServer | Where-Object { $_.State -like "Running" }) {
            Stop-VM $VM2Name -ComputerName $HvServer -Force
            if (-not $?) {
                Write-LogErr "Unable to shut $VM2Name down (in order to add a new network Adapter)"
                return $False
            }

            if ($null -ne $checkpointName) {
                Restore-VMSnapshot -Name $checkpointName -VMName $VM2Name -Confirm:$false `
                    -ComputerName $HvServer
                if (-not $?) {
                    Write-LogErr "Unable to restore checkpoint $checkpointName on $VM2Name"
                    return $False
                }
            }
        }

        .\Testscripts\Windows\SETUP-NET-Add-NIC.ps1 -TestParams $vm2NicAddParam -VMName $VM2Name
        if (-not $?) {
            Write-LogErr "Cannot add new NIC to $VM2Name"
            return $False
        }
    } else {
        Write-LogErr "Could not find Testscripts\Windows\SETUP-NET-Add-NIC.ps1 ."
        return $False
    }

    # Get the newly added NIC
    $vm2nic = Get-VMNetworkAdapter -VMName $VM2Name -ComputerName $HvServer -IsLegacy:$False | Where-Object { $_.MacAddress -like "$vm2MacAddress" }
    if (-not $vm2nic) {
        Write-LogErr "Could not retrieve the newly added NIC to VM2"
        return $False
    }

    # Start VM2 & retrieve the ipv4
    $vm2ipv4 = Start-VMandGetIP $VM2Name $HvServer $VMPort $VMUserName $VMPassword

    # Configure the newly added NIC
    if (-not $vm2MacAddress.Contains(":")) {
        for ($i=2; $i -lt 16; $i=$i+2) {
            $vm2MacAddress = $vm2MacAddress.Insert($i,':')
            $i++
        }
    }
    if ($vlanId) {
        $null = Set-GuestInterface -VMUser $guestUsername -VMIpv4 $vm2ipv4 -VMPort $VMPort `
            -VMPassword $VMPassword -InterfaceMAC $vm2MacAddress -VMStaticIP $vm2StaticIP `
            -Netmask $netmask -VMName $VM2Name -VlanID $vlanID
    } else {
        $null = Set-GuestInterface $guestUsername $vm2ipv4 $VMPort $VMPassword $vm2MacAddress `
            $vm2StaticIP $bootproto $netmask $VM2Name
    }

    if (-not $?) {
        return $False
    }

    return $True
}

Main -VMName $AllVMData.RoleName -HvServer $xmlConfig.config.Hyperv.Hosts.ChildNodes[0].ServerName `
     -VMPort $AllVMData.SSHPort -VMUserName $user -VMPassword $password `
     -TestParams $TestParams
