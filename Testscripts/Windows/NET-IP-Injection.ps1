# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Synopsis
    This script tests ip injection from host to guest functionality
#>

param([string] $TestParams)
$NamespaceV2 = "root\virtualization\v2"

# Checks if hv_set_ifconfig is present in the VM
function Get-HvSetConfig() {
    $sts = RunLinuxCmd -username "root" -password $VMPassword -ip $Ipv4 -port $VMPort `
        -command "find /usr/|grep hv_set_ifconfig" -ignoreLinuxExitCode:$true
    if (-not $sts) {
        LogErr "hv_set_ifconfig is not present or verification failed"
        break
    }
    LogMsg "hv_set_ifconfig is present in the VM"
}

# Monitors Msvm_ConcreteJob.
function Watch-Job($opresult) {
    if ($opresult.ReturnValue -eq 0) {
        return
    } elseif ($opresult.ReturnValue -ne 4096) {
        LogMsg "Error code: $(($opresult).ReturnValue)"
        return
    } else {
        # Find the job to monitor status
        $jobid = $opresult.Job.Split('=')[1]
        $concreteJob = Get-WmiObject -Query "select * from CIM_ConcreteJob where InstanceId=$jobid" -namespace $NamespaceV2 -ComputerName $HvServer
        $top = [Console]::CursorTop
        $left = [Console]::CursorLeft

        #Loop till job not complete
        if ($null -ne $concreteJob -AND
            ($concreteJob.PercentComplete -ne 100) -AND
            ($concreteJob.ErrorCode -eq 0)
            ) {
            Start-Sleep -Milliseconds 500
            # Following is to show progress on same position for powershell cmdline host
            if (!(get-variable  -erroraction silentlycontinue "psISE")) {
                [Console]::SetCursorPosition($left, $top)
            }
            Watch-Job $opresult
        }
    }
}

function Get-NullAndExit([System.Object[]] $object, [string] $message) {
    if ($null -eq $object) {
        LogErr $message
        exit 1
    }
    return
}

function Get-SingleObject([System.Object[]] $objects, [string] $message) {
    if ($objects.Length -gt 1) {
        LogErr $message
        exit 1
    }
    return
}

# Get VM object
function Get-VirtualMachine([string] $VMName) {
    $objects = Get-WmiObject -Namespace $NamespaceV2 -Query "Select * From Msvm_ComputerSystem Where ElementName = '$VMName' OR Name = '$VMName'" -computername $HvServer
    if ($null -eq $objects) {
        LogMsg "Erorr: Virtual Machine not found"
        exit 1
    }

    Get-NullAndExit $objects "Failed to find VM object for $VMName"
    if ($objects.Length -gt 1) {
        foreach ($objItem in $objects) {
            LogMsg "ElementName: $(($objItem).ElementName)"
            LogMsg "Name: $(($objItem).Name)"
        }
        Get-SingleObject $objects "Multiple VM objects found for name $VMName. This script doesn't support this. Use Name GUID as VmName parameter."
    }
    return [System.Management.ManagementObject] $objects
}

# Get VM Service object
function Get-VmServiceObject() {
    $objects = Get-WmiObject -Namespace $NamespaceV2  -Query "Select * From Msvm_VirtualSystemManagementService" -computername $HvServer
    Get-NullAndExit $objects "Failed to find VM service object"
    Get-SingleObject $objects "Multiple VM Service objects found"
    return $objects
}

# Find first Msvm_GuestNetworkAdapterConfiguration instance.
function Get-GuestNetworkAdapterConfiguration($VMName) {
    $VM = Get-WmiObject -Namespace root\virtualization\v2 -class Msvm_ComputerSystem -ComputerName $HvServer | Where-Object {$_.ElementName -like $VMName}
    Get-NullAndExit $VM "Failed to find VM instance"

    # Get active settings
    $vmSettings = $vm.GetRelated( "Msvm_VirtualSystemSettingData", "Msvm_SettingsDefineState",$null,$null, "SettingData", "ManagedElement", $false, $null)

    # Get all network adapters
    $nwAdapters = $vmSettings.GetRelated("Msvm_SyntheticEthernetPortSettingData")

    # Find associated guest configuration data
    $nwconfig = ($nwadapters.GetRelated("Msvm_GuestNetworkAdapterConfiguration", "Msvm_SettingDataComponent", $null, $null, "PartComponent", "GroupComponent", $false, $null) | ForEach-Object {$_})

    if ($null -eq $nwconfig) {
        LogMsg "Failed to find Msvm_GuestNetworkAdapterConfiguration instance. Creating new instance."
    }
    return $nwconfig;
}

function Set-IpOnVM {
    param (
        $IPv4Address,
        $DHCPEnabled,
        $IPv4subnet,
        $DnsServer,
        $IPv4Gateway,
        $ProtocolIFType
    )
    $colItems = Get-WmiObject -class "Win32_NetworkAdapterConfiguration" -namespace "root\CIMV2" -ComputerName $HvServer
    foreach ($objItem in $colItems) {
        if ($null -ne $objItem.DNSHostName) {
            $netAdp = get-wmiobject -class "Win32_NetworkAdapter" -Filter "GUID=`'$($objItem.SettingID)`'" -namespace "root\CIMV2" -ComputerName $HvServer
            if ($netAdp.NetConnectionID -like '*External*'){
                $IPv4subnet = $objItem.IPSubnet[0]
                $IPv4Gateway = $objItem.DefaultIPGateway[0]
                $DnsServer = $objItem.DNSServerSearchOrder[0]
            }
        }
    }

    # Get the VMs IP addresses before injecting, then make sure the
    # address we are to inject is not already assigned to the VM.
    $vmNICs = Get-VMNetworkAdapter -vmName $VMName -ComputerName $HvServer
    $ipAddrs = @()
    foreach( $nic in $vmNICS) {
        foreach ($addr in $nic.IPAddresses) {
            $ipaddrs += $addr
        }
    }

    if ($ipAddrs -contains $IPv4Address) {
        LogErr "The VM is already assigned address '${IPv4Address}'"
        exit 1
    }
    LogMsg "IP $IPv4Address will be injected in place of $IPv4"

    # Collect WMI objects for the virtual machine we are interested in
    # so we can inject some IP setting into the VM.
    [System.Management.ManagementObject] $vm = Get-VirtualMachine($VMName)
    [System.Management.ManagementObject] $vmservice = @(Get-VmServiceObject)[0]
    [System.Management.ManagementObject] $nwconfig = @(Get-GuestNetworkAdapterConfiguration($VMName))[0];

    # Fill in the IP address data we want to inject
    $nwconfig.DHCPEnabled = $DHCPEnabled
    $nwconfig.IPAddresses = @($IPv4Address)
    $nwconfig.Subnets = @($IPv4Subnet)
    $nwconfig.DefaultGateways = @($IPv4Gateway)
    $nwconfig.DNSServers = @($DnsServer)

    # Note: Address family values for settings IPv4 , IPv6 Or Boths
    #   For IPv4:    ProtocolIFType = 4096;
    #   For IPv6:    ProtocolIFType = 4097;
    #   For IPv4/V6: ProtocolIFType = 4098;
    $nwconfig.ProtocolIFType = $ProtocolIFType

    # Inject the IP data into the VM
    $opresult = $vmservice.SetGuestNetworkAdapterConfiguration($vm.Path, @($nwconfig.GetText(1)))
    Watch-Job($opresult)
}

# Main script body
function Main {
    param (
        $VMName,
        $HvServer,
        $IPv4,
        $VMPort,
        $VMUserName,
        $VMPassword,
        $TestParams
    )
    $DHCPEnabled = $False
    $ProtocolIFType = 4096

    LogMsg "Test parameters: $TestParams"
    $params = $TestParams.Split(';')
    foreach ($p in $params) {
        $fields = $p.Split("=")
        switch ($fields[0].Trim()) {
            "dhcpenabled" { $DHCPEnabled = $fields[1].Trim() }
            "ipv4address" { $IPv4Address = $fields[1].Trim() }
            "ipv4subnet" { $IPv4subnet = $fields[1].Trim() }
            "dnsserver" { $DnsServer = $fields[1].Trim() }
            "ipv4Gateway" { $IPv4Gateway = $fields[1].Trim() }
            "protocoliftype" { $ProtocolIFType = $fields[1].Trim() }
            default {}
        }
    }
    # Check if hv_set_ifconfig is on the VM
    Get-HvSetConfig

    $isPassed= $false
    for ($i=0; $i -le 2; $i++) {
        Set-IpOnVM $IPv4Address $DHCPEnabled $IPv4subnet $DnsServer $IPv4Gateway $ProtocolIFType
        #
        # Now collect the IP addresses assigned to the VM and make
        # sure the injected address is in the list.
        #
        Start-Sleep 20
        $vmNICs = Get-VMNetworkAdapter -vmName $VMName -ComputerName $HvServer
        $ipAddrs = @()
        foreach( $nic in $vmNICS) {
            foreach ($addr in $nic.IPAddresses) {
                $ipaddrs += $addr
            }
        }

        if ($ipAddrs -notcontains $IPv4Address) {
            LogMsg "The address '${IPv4Address}' was not injected into the VM. `n"
        } else{
            LogMsg "The address '${IPv4Address}' was successfully injected into the VM. `n"
            $isPassed = $true
            break
        }
    }

    if ($isPassed -eq $false) {
        LogErr "All attempts failed"
        return "FAIL"
    }

    LogMsg "IP Injection test passed"
    return "PASS"
}

Main -VMName $AllVMData.RoleName -HvServer $xmlConfig.config.Hyperv.Hosts.ChildNodes[0].ServerName `
    -IPv4 $AllVMData.PublicIP -VMPort $AllVMData.SSHPort -VMUserName $user `
    -VMPassword $password -TestParams $TestParams