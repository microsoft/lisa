# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Synopsis
    Use two VMs to test a Private Network.
    Dependency VM is configured by the setupScript. Test VM is configured
    by this script. AFter the config is done, several ping tests will
    be performed

    If the above ping succeeded, the test passed.
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
        $IPv4,
        $TestParams
    )
    $packetNumber = "11"
    $switchNic = $null
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
            "VM2Name" { $VM2Name = $fields[1].Trim() }
            "STATIC_IP" { $vm1StaticIP = $fields[1].Trim() }
            "STATIC_IP2" { $vm2StaticIP = $fields[1].Trim() }
            "PING_FAIL" { $failIP1 = $fields[1].Trim() }
            "PING_FAIL2" { $failIP2 = $fields[1].Trim() }
            "SWITCH" { $switchNic = $fields[1].Trim() }
            "NETMASK" { $netmask = $fields[1].Trim() }
            "AddressFamily" {
                if ($fields[1].Trim() -eq "IPv6"){
                    $pingVersion="ping6"
                } else {
                    $pingVersion="ping"
                }
            }
        }
    }

    # Switch network connection type in case is needed
    if ($switchNic) {
        # Switch the NIC on test VM from External to Private
        $retVal = .\Testscripts\Windows\SETUP-NET-Switch-NIC.ps1 -VMName $VMName -testParams "SWITCH=$switchNic"
        if (-not $retVal) {
            Write-LogErr "Failed to switch connection type for $VMName on $HvServer"
            return "FAIL"
        }

        # Switch the NIC on dependency VM from External to Private
        $switchNic = $switchNic+","+$vm2MacAddress
        $retVal = .\Testscripts\Windows\SETUP-NET-Switch-NIC.ps1 -VMName $VM2Name -testParams "SWITCH=$switchNic"
        if (-not $retVal) {
            Write-LogErr "Failed to switch connection type for $VM2Name on $HvServer"
            return "FAIL"
        }
    }

    Write-LogInfo "Setting up the net adapter on guest $VMName"
    if (-not $vm1MacAddress.Contains(":")) {
        for ($i=2; $i -lt 16; $i=$i+2) {
            $vm1MacAddress = $vm1MacAddress.Insert($i,':')
            $i++
        }
    }
    $retVal = Set-GuestInterface $VMUserName $IPv4 $VMPort $VMPassword $vm1MacAddress `
        $vm1StaticIP $bootproto $netmask $VMName
    if (-not $?) {
        Write-LogErr "Couldn't configure the test interface on $VMName"
        return "FAIL"
    }

    # Try to ping with the private network interfaces. This should pass
    $retVal = Test-GuestInterface $VMUserName $vm2StaticIP $IPv4 $VMPort $VMPassword `
        $vm1MacAddress $pingVersion $packetNumber
    if ($retVal -eq $False) {
        Write-LogErr "Could not $pingVersion from $vm1StaticIP to $vm2StaticIP"
        return "FAIL"
    } else {
        Write-LogInfo "$pingVersion from $vm1StaticIP to $vm2StaticIP was successful"
    }

    # Try to ping a wrong IP
    $retVal = Test-GuestInterface $VMUserName $failIP1 $IPv4 $VMPort $VMPassword `
        $vm1MacAddress $pingVersion $packetNumber
    if ($retVal -eq $True) {
        Write-LogErr "$pingVersion from $vm1StaticIP to $failIP1 shouldn't have worked"
        return "FAIL"
    } else {
        Write-LogInfo "$pingVersion from $vm1StaticIP to $failIP1 failed - AS EXPECTED -"
    }

    $retVal = Test-GuestInterface $VMUserName $failIP2 $IPv4 $VMPort $VMPassword `
        $vm1MacAddress $pingVersion $packetNumber
    if ($retVal -eq $True) {
        Write-LogErr "$pingVersion from $vm1StaticIP to $failIP2 shouldn't have worked"
        return "FAIL"
    } else {
        Write-LogInfo "$pingVersion from $vm1StaticIP to $failIP1 failed - AS EXPECTED -"
    }
    return "PASS"
}

Main -VMName $AllVMData.RoleName -HvServer $GlobalConfig.Global.Hyperv.Hosts.ChildNodes[0].ServerName `
     -VMPort $AllVMData.SSHPort -VMUserName $user -VMPassword $password `
     -IPv4 $AllVMData.PublicIP -TestParams $TestParams
