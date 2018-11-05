# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Synopsis
 Run the VLAN Trunking test.

 Description:
    Use two VMs to test the VLAN trunking feature.
    The first VM is started by the LIS framework, while the second one
    will be managed by this script.

    The script expects a NIC param in the same format as the
    NET_{ADD|REMOVE|SWITCH}_NIC_MAC.ps1 scripts. It checks both VMs
    for a NIC connected to the specified network. If the first VM's NIC
    is not found, test will fail. In case the second VM is missing
    this NIC, it will call the NET_ADD_NIC_MAC.ps1 script directly
    and add it. If the NIC was added by this script, it will also clean-up
    after itself, unless the LEAVE_TRAIL param is set to `YES'.

    After both VMs are up, this script will configure each NIC inside the VM
    to use VLANs with the VM_VLAN_ID parameter. Then it will configure the
    NetAdapters to trunk mode and try to ping the other VM.

    If the above ping succeeded, the second VM will change its vlan ID and try
     to ping the first VM again. This must fail.
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
    $packetNumber = "11"
    $testIPv6 = "no"
    $currentDir = "$((Get-Location).Path)\"
    $guestUsername = "root"

    # Get MAC for test VM NIC
    $macFileTestVM = "macAddress.file"
    $macFileTestVM = "$currentDir"+"$macFileTestVM"
    $streamReaderTestVM = [System.IO.StreamReader] $macFileTestVM
    $vm1MacAddress = $streamReaderTestVM.ReadLine()
    LogMsg "vm1 MAC: $vm1MacAddress"
    $streamReaderTestVM.close()

    # Get MAC for dependency VM
    $macFileDependencyVM = "macAddressDependency.file"
    $macFileDependencyVM ="$currentDir"+"$macFileDependencyVM"
    $streamReaderDependencyVM = [System.IO.StreamReader] $macFileDependencyVM
    $vm2MacAddress = $streamReaderDependencyVM.ReadLine()
    LogMsg "vm2 MAC: $vm2MacAddress"
    $streamReaderDependencyVM.close()

    $params = $TestParams.Split(';')
    foreach ($p in $params) {
        $fields = $p.Split("=")
        switch ($fields[0].Trim()) {
            "VM2Name" { $VM2Name = $fields[1].Trim() }
            "VM_VLAN_ID" { $vlanId = $fields[1].Trim() }
            "NATIVE_VLAN_ID" { $nativeVlanId = $fields[1].Trim() }
            "STATIC_IP" { $vm1StaticIP = $fields[1].Trim() }
            "STATIC_IP2" { $vm2StaticIP = $fields[1].Trim() }
            "NETMASK" { $netmask = $fields[1].Trim() }
            "NIC" {
                $nicArgs = $fields[1].Split(',')
                if ($nicArgs.Length -lt 3) {
                    LogErr "Incorrect number of arguments for NIC test parameter: $p"
                    return "FAIL"
                }
                $nicType = $nicArgs[0].Trim()
                $networkType = $nicArgs[1].Trim()
                $networkName = $nicArgs[2].Trim()
                if ($nicArgs.Length -eq 4) {
                    $vm1MacAddress = $nicArgs[3].Trim()
                }
                # Validate the network adapter type
                if ("NetworkAdapter" -notcontains $nicType) {
                    LogErr "Invalid NIC type: $nicType . Must be 'NetworkAdapter'"
                    return "FAIL"
                }
                # Validate the Network type
                if (@("External", "Internal", "Private") -notcontains $networkType) {
                    LogErr "Invalid network type: $networkType . Network type must be either: External, Internal or Private"
                    return "FAIL"
                }
                # Make sure the network exists
                $vmSwitch = Get-VMSwitch -Name $networkName -ComputerName $HvServer
                if (-not $vmSwitch) {
                    LogErr "Invalid network name: $networkName . The network does not exist."
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

    # Get the NICs from both VMs and set them in untagged mode
    $vm1nic = Get-VMNetworkAdapter -VMName $VMName -ComputerName $HvServer -IsLegacy:$false | Where-Object {$_.MacAddress -eq $vm1MacAddress }
    if ($vm1nic) {
        "$VMName found NIC with MAC $vm1MacAddress"
        Set-VMNetworkAdapterVlan -VMNetworkAdapter $vm1nic -Untagged
    } else {
        LogErr "$VMName - No NIC found with MAC $vm1MacAddress"
        return "FAIL"
    }
    $vm2nic =  Get-VMNetworkAdapter -VMName $VM2Name -ComputerName $HvServer -IsLegacy:$false | Where-Object {$_.MacAddress -eq $vm2MacAddress }
    if ($vm2nic) {
        "$VM2Name found NIC with MAC $vm1MacAddress"
        Set-VMNetworkAdapterVlan -VMNetworkAdapter $vm2nic -Untagged
    } else {
        LogErr "$VM2Name - No NIC found with MAC $vm1MacAddress"
        return "FAIL"
    }

    # Get IPs from both VMs
    $ipv4 = Get-IPv4ViaKVP $VMName $HvServer

    # Convert MAC adress
    if (-not $vm1MacAddress.Contains(":")) {
        for ($i=2; $i -lt 16; $i=$i+2) {
            $vm1MacAddress = $vm1MacAddress.Insert($i,':')
            $i++
        }
    }
    if (-not $vm2MacAddress.Contains(":")) {
        for ($i=2; $i -lt 16; $i=$i+2) {
            $vm2MacAddress = $vm2MacAddress.Insert($i,':')
            $i++
        }
    }

    # Create vlan on both VMs
    $retVal = Set-GuestInterface -VMUser $guestUsername -VMIpv4 $ipv4 -VMPort $VMPort `
        -VMPassword $VMPassword -InterfaceMAC $vm1MacAddress -VMStaticIP $vm1StaticIP `
        -Netmask $netmask -VMName $VMName -VlanID $vlanID
    if (-not $?) {
        LogErr "Couldn't configure the test interface on $VMName"
        return "FAIL"
    }
    
    # Try to ping. If it fails, restart the vm & try again
    $retVal = Test-GuestInterface $guestUsername $vm2StaticIP $ipv4 $VMPort $VMPassword `
        $vm1MacAddress $pingVersion $packetNumber "yes"
    if ($retVal -eq $True) {
        LogErr "$pingVersion should have failed from $vm1StaticIP to $vm2StaticIP"
        return "FAIL"
    } else {
        LogMsg "$pingVersion from $vm1StaticIP to $vm2StaticIP failed - AS EXPECTED -"
    }

    # Set trunk mode on both NICs. Ping should start working
    Set-VMNetworkAdapterVlan -VMNetworkAdapter $vm1nic -Trunk -AllowedVlanIdList $vlanID -NativeVlanId $nativeVlanId
    if (-not $?) {
        LogErr "Failed to put $vm1nic in trunk mode"
        return "FAIL"
    }
    Set-VMNetworkAdapterVlan -VMNetworkAdapter $vm2nic -Trunk -AllowedVlanIdList $vlanID -NativeVlanId $nativeVlanId
    if (-not $?) {
        LogErr "Failed to put $vm2nic in trunk mode"
        return "FAIL"
    }

    $retVal = Test-GuestInterface $guestUsername $vm2StaticIP $ipv4 $VMPort $VMPassword `
        $vm1MacAddress $pingVersion $packetNumber "yes"
    if ($retVal -eq $False) {
        LogErr "Could not $pingVersion from $vm1StaticIP to $vm2StaticIP"
        return "FAIL"
    } else {
        LogMsg "$pingVersion from $vm1StaticIP to $vm2StaticIP was successful"
    }

    # Change vlan ID. Ping Should fail
    $badVlanId = [int]$vlanID + [int]1
    Set-VMNetworkAdapterVlan -VMNetworkAdapter $vm1nic -Trunk -AllowedVlanIdList $badVlanId -NativeVlanId $nativeVlanId
    if (-not $?) {
        LogErr "Failed to put $vm1nic in trunk mode"
        return "FAIL"
    }
    Set-VMNetworkAdapterVlan -VMNetworkAdapter $vm2nic -Trunk -AllowedVlanIdList $badVlanId -NativeVlanId $nativeVlanId
    if (-not $?) {
        LogErr "Failed to put $vm2nic in trunk mode"
        return "FAIL"
    }

    $retVal = Test-GuestInterface $guestUsername $vm2StaticIP $ipv4 $VMPort $VMPassword `
        $vm1MacAddress $pingVersion $packetNumber "yes"
    if ($retVal -eq $True) {
        LogErr "$pingVersion should have failed from $vm1StaticIP to $vm2StaticIP"
        return "FAIL"
    } else {
        LogMsg "$pingVersion from $vm1StaticIP to $vm2StaticIP failed - AS EXPECTED -"
    }

    LogMsg "SUCCESS: Test Passed"
    return "PASS"
}

Main -VMName $AllVMData.RoleName -HvServer $xmlConfig.config.Hyperv.Hosts.ChildNodes[0].ServerName `
     -VMPort $AllVMData.SSHPort -VMUserName $user -VMPassword $password `
     -TestParams $TestParams