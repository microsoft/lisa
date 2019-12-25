# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Synopsis
    Use two VMs to test the VLAN tagging (access) feature.
#>

param([String] $TestParams,
      [object] $AllVmData)

function Main {
    param (
        $VMName,
        $HvServer,
        $VMPort,
        $VMUserName,
        $VMPassword,
        $TestParams
    )
    $packetNumber = "11"
    $testIPv6 = "no"
    $bootproto = "static"
    $currentDir = "$pwd\"

    # Get MAC for test VM NIC
    $macFileTestVM = "macAddress.file"
    $macFileTestVM = "$currentDir"+"$macFileTestVM"
    $streamReaderTestVM = [System.IO.StreamReader] $macFileTestVM
    $vm1MacAddress = $streamReaderTestVM.ReadLine()
    Write-LogInfo "vm1 MAC: $vm1MacAddress"
    $streamReaderTestVM.close()
    # Get MAC for dependency VM
    $macFileDependencyVM = "macAddressDependency.file"
    $macFileDependencyVM ="$currentDir"+"$macFileDependencyVM"
    $streamReaderDependencyVM = [System.IO.StreamReader] $macFileDependencyVM
    $vm2MacAddress = $streamReaderDependencyVM.ReadLine()
    Write-LogInfo "vm2 MAC: $vm2MacAddress"
    $streamReaderDependencyVM.close()

    $params = $TestParams.Split(';')
    foreach ($p in $params) {
        $fields = $p.Split("=")
        switch ($fields[0].Trim()) {
        "VM2NAME" { $vm2Name = $fields[1].Trim() }
        "VLAN_ID" { $vlanId = $fields[1].Trim() }
        "TestIPV6" { $testIPv6 = $fields[1].Trim() }
        "STATIC_IP" { $vm1StaticIP = $fields[1].Trim() }
        "STATIC_IP2" { $vm2StaticIP = $fields[1].Trim() }
        "NETMASK" { $netmask = $fields[1].Trim() }
        "NIC_1" {
            $nicArgs = $fields[1].Split(',')
            if ($nicArgs.Length -lt 3) {
                Write-LogErr "Incorrect number of arguments for NIC test parameter: $p"
                return "FAIL"
            }
            $nicType = $nicArgs[0].Trim()
            $networkType = $nicArgs[1].Trim()
            $networkName = $nicArgs[2].Trim()

            # Validate the network adapter type
            if ("NetworkAdapter" -notcontains $nicType) {
                Write-LogErr "Invalid NIC type: $nicType . Must be 'NetworkAdapter'"
                return "FAIL"
            }

            # Validate the Network type
            if (@("External", "Internal", "Private") -notcontains $networkType) {
                Write-LogErr "Invalid netowrk type: $networkType .  Network type must be either: External, Internal, Private"
                return "FAIL"
            }

            # Make sure the network exists
            $vmSwitch = Get-VMSwitch -Name $networkName -ComputerName $HvServer
            if (-not $vmSwitch) {
                Write-LogErr "Invalid network name: $networkName . The network does not exist."
                return "FAIL"
            }
        }
        default {}
        }
    }

    if ( $testIPv6 -eq "yes" ) {
        $pingVersion = "ping6"
    } else {
        $pingVersion = "ping"
    }

    # Get the NICs from both VMs
    $vm1nic = Get-VMNetworkAdapter -VMName $VMName -ComputerName $HvServer -IsLegacy:$false | Where-Object {$_.MacAddress -eq $vm1MacAddress }
    if ($vm1nic) {
        "$VMName found NIC with MAC $vm1MacAddress ."
    } else {
        Write-LogErr "$VMName - No NIC found with MAC $vm1MacAddress ."
        return "FAIL"
    }
    $vm2nic =  Get-VMNetworkAdapter -VMName $VM2Name -ComputerName $HvServer -IsLegacy:$false | Where-Object {$_.MacAddress -eq $vm2MacAddress }
    if ($vm2nic) {
        "$VM2Name found NIC with MAC $vm1MacAddress ."
    } else {
        Write-LogErr "$VM2Name - No NIC found with MAC $vm1MacAddress ."
        return "FAIL"
    }

    # VM 2 NIC was configred by the setupscript. We need to configure
    # the test VM NIC
    Write-LogInfo "Setting up the net adapter on guest $VMName"
    if (-not $vm1MacAddress.Contains(":")) {
        for ($i=2; $i -lt 16; $i=$i+2) {
            $vm1MacAddress = $vm1MacAddress.Insert($i,':')
            $i++
        }
    }
    $IPv4 = Get-IPv4ViaKVP $VMName $HvServer
    $retVal = Set-GuestInterface $VMUserName $IPv4 $VMPort $VMPassword $vm1MacAddress `
        $vm1StaticIP $bootproto $netmask $VMName
    if (-not $?) {
        Write-LogErr "Couldn't configure the test interface on $VMName"
        return "FAIL"
    }

    # Test interface without any vlan tags
    $retVal = Test-GuestInterface $VMUserName $vm2StaticIP $IPv4 $VMPort $VMPassword `
        $vm1MacAddress $pingVersion $packetNumber
    if ($retVal -eq $False) {
        Write-LogErr "Could not $pingVersion from $vm1StaticIP to $vm2StaticIP"
        return "FAIL"
    } else {
        Write-LogInfo "$pingVersion from $vm1StaticIP to $vm2StaticIP was successful"
    }

    # Set vlan only on first VM. Ping between VMs should fail
    Write-LogInfo "Setting $VMName test NIC to access mode with vlanID $vlanID"
    Set-VMNetworkAdapterVlan -VMNetworkAdapter $vm1Nic -Access -VlanID $vlanID
    if (-not $?) {
        Write-LogErr "Failed to set $vm1Nic to Access Mode with a VlanID of $vlanID"
        return "FAIL"
    }
    Write-LogInfo "Successfully configured $vm1Nic"
    Start-Sleep -Seconds 10

    $retVal = Test-GuestInterface $VMUserName $vm2StaticIP $IPv4 $VMPort $VMPassword `
        $vm1MacAddress $pingVersion $packetNumber
    if ($retVal -eq $True) {
        Write-LogErr "$pingVersion should have failed from $vm1StaticIP to $vm2StaticIP"
        return "FAIL"
    } else {
        Write-LogInfo "$pingVersion from $vm1StaticIP to $vm2StaticIP failed - AS EXPECTED -"
    }

    # Set same vlan on dependency VM. Ping between VMs should work again
    Write-LogInfo "Setting $vm2Name test NIC to access mode with vlanID $vlanID"
    Set-VMNetworkAdapterVlan -VMNetworkAdapter $vm2nic -Access -VlanID $vlanID
    if (-not $?) {
        Write-LogErr "Failed to set $vm2nic to Access Mode with an VlanID of $vlanID"
        return "FAIL"
    }
    Write-LogInfo "Successfully configured $vm2nic"
    Start-Sleep -Seconds 10

    $retVal = Test-GuestInterface $VMUserName $vm2StaticIP $IPv4 $VMPort $VMPassword `
        $vm1MacAddress $pingVersion $packetNumber
    if ($retVal -eq $False) {
        Write-LogErr "Could not $pingVersion from $vm1StaticIP to $vm2StaticIP"
        return "FAIL"
    } else {
        Write-LogInfo "$pingVersion from $vm1StaticIP to $vm2StaticIP was successful"
    }

    # Change vlan on test VM. Ping between VMs should fail
    Write-LogInfo "Setting $VMName test NIC to access mode with vlanID $vlanID"
    Set-VMNetworkAdapterVlan -VMNetworkAdapter $vm1Nic -Access -VlanID "1"
    if (-not $?) {
        Write-LogErr "Failed to set $vm1Nic to Access Mode with a VlanID of $vlanID"
        return "FAIL"
    }
    Write-LogInfo "Successfully configured $vm1Nic"
    Start-Sleep -Seconds 10
    $retVal = Test-GuestInterface $VMUserName $vm2StaticIP $IPv4 $VMPort $VMPassword `
        $vm1MacAddress $pingVersion $packetNumber
    if ($retVal -eq $True) {
        Write-LogErr "$pingVersion should have failed from $vm1StaticIP to $vm2StaticIP"
        return "FAIL"
    } else {
        Write-LogInfo "$pingVersion from $vm1StaticIP to $vm2StaticIP failed - AS EXPECTED -"
    }

    Write-LogInfo "Test successful! Ping worked as expected in every case"
    return "PASS"
}

Main -VMName $AllVMData.RoleName -HvServer $GlobalConfig.Global.Hyperv.Hosts.ChildNodes[0].ServerName `
     -VMPort $AllVMData.SSHPort -VMUserName $user -VMPassword $password `
     -TestParams $TestParams
