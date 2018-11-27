# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Synopsis
    Enable SR-IOV on VM

.Description
    This is a setupscript that enables SR-IOV on VM
    Steps:
    1. Add new NICs to VMs
    2. Configure/enable SR-IOV on VMs settings via cmdlet Set-VMNetworkAdapter
    3. Set up SR-IOV on VM2
    Optional: Set up an internal network on VM2
#>
param ([string] $TestParams)
function Set-VFInGuest {
    param (
        $VMUser,
        $VMIp,
        $VMPass,
        $VMPort,
        $VMName,
        $VMNumber,
        $VfIPToCheck
    )
    # Upload sriov_constants.sh
    Copy-RemoteFiles -upload -uploadTo $VMIp -Port $VMPort `
        -files "sriov_constants.sh" -Username $VMUser -password $VMPass
    if (-not $?) {
        Write-LogErr "Failed to send sriov_constants.sh to VM1!"
        return $False
    }
    RunLinuxCmd -username $VMUser -password $VMPass -ip $VMIp -port $VMPort -command "cp sriov_constants.sh constants.sh"
    # Install dependencies
    Run-LinuxCmd -username $VMUser -password $VMPass -ip $VMIp -port $VMPort -command ". SR-IOV-Utils.sh; InstallDependencies"
    if (-not $?) {
        Write-LogErr "Failed to install dependencies on $VMName"
        return $False
    }
    # Configure VF
    RunLinuxCmd -username $VMUser -password $VMPass -ip $VMIp -port $VMPort -command ". SR-IOV-Utils.sh; ConfigureVF $VMNumber"
    if (-not $?) {
        LogErr "Failed to configure VF on $VMName"
        return $False
    }
    # Check VF
    $retVal = Run-LinuxCmd -username $VMUser -password $VMPass -ip $VMIp -port $VMPort -command "ip a | grep -c $VfIPToCheck" -ignoreLinuxExitCode:$true
    if ($retVal -ne 1) {
        Write-LogErr "IP is not set on $VMName"
        return $False
    }
    Run-LinuxCmd -username $VMUser -password $VMPass -ip $VMIp -port $VMPort -command "rm -f constants.sh"
    return $True
}

function Main {
    param (
        $VMName,
        $HvServer,
        $VMPort,
        $VMUsername,
        $VMPassword,
        $TestParams
    )
    # Main script body
    $maxNICs = "no"
    $nicIterator = 0
    $vfIP = @()
    $vfIterator = 0
    $VMRootUser = "root"

    $params = $TestParams.Split(';')
    foreach ($p in $params) {
        $fields = $p.Split("=")
        switch ($fields[0].Trim()) {
            "NIC_COUNT" { $nicIterator = $fields[1].Trim()}
            "VM2NAME" { $VM2Name = $fields[1].Trim() }
            "VF_IP1" {
                $vfIP1 = $fields[1].Trim()
                $vfIP += ($vfIP1)
                $vfIterator++ }
            "VF_IP2" {
                $vfIP2 = $fields[1].Trim()
                $vfIP += ($vfIP2)
                $vfIterator++ }
            "VF_IP3" {
                $vfIP3 = $fields[1].Trim()
                $vfIP += ($vfIP3)
                $vfIterator++ }
            "VF_IP4" {
                $vfIP4 = $fields[1].Trim()
                $vfIP += ($vfIP4)
                $vfIterator++ }
            "MAX_NICS" { $maxNICs = $fields[1].Trim() }
            "NETMASK" { $netmask = $fields[1].Trim() }
            "CheckpointName" { $checkpointName = $fields[1].Trim() }
            "Switch_Name"{ $networkName = $fields[1].Trim()}
            default {}
        }
    }

    if ($maxNICs -eq "yes") {
        $nicIterator = 7
        $vfIterator = 14
    }

    if (-not $VM2Name) {
        Write-LogErr "Test parameter vm2Name was not specified"
        return $False
    }

    if (-not $networkName) {
        Write-LogErr "Test parameter Switch_Name was not specified"
        return $False
    }

    # Verify VM2 exists & restore the snapshot
    $vm2 = Get-VM -Name $VM2Name -ComputerName $DependencyVmHost -EA SilentlyContinue
    if (-not $vm2) {
        Write-LogErr "VM ${vm2Name} does not exist"
        return $False
    }

    if (Get-VM -Name $VM2Name -ComputerName $DependencyVmHost | Where-Object { $_.State -like "Running" }) {
        Stop-VM $VM2Name -ComputerName $DependencyVmHost -Force -TurnOff
        if (-not $?) {
            Write-LogErr "Unable to shut $VM2Name down (in order to add a new network Adapter)"
            return $False
        }
    }
    if ($null -ne $checkpointName) {
        Restore-VMSnapshot -Name $checkpointName -VMName $VM2Name -Confirm:$false `
            -ComputerName $DependencyVmHost
        if (-not $?) {
            Write-LogErr "Unable to restore checkpoint $checkpointName on $VM2Name"
            return $False
        }
    }

    # Add NICs to both VMs
    for ($i=0; $i -lt $nicIterator; $i++){
        Add-VMNetworkAdapter -VMName $VMName -SwitchName $networkName -IsLegacy:$false -ComputerName $HvServer
        if ($? -ne "True") {
            Write-LogErr "Add-VmNic to $VMName failed"
            return $False
        }

        Add-VMNetworkAdapter -VMName $VM2Name -SwitchName $networkName -IsLegacy:$false -ComputerName $DependencyVmHost
        if ($? -ne "True") {
            Write-LogErr "Add-VmNic to $VM2Name failed"
            return $False
        }
    }

    # Enable SR-IOV on both VMs
    Set-VMNetworkAdapter -VMName $VMName -ComputerName $HvServer -IovWeight 1
    if ($? -ne "True") {
        Write-LogErr "Failed to enable SR-IOV on $VMName!"
        return $False
    }
    Set-VMNetworkAdapter -VMName $VM2Name -ComputerName $DependencyVmHost -IovWeight 1
    if ($? -ne "True") {
        Write-LogErr "Failed to enable SR-IOV on $VMName!"
        return $False
    }

    # Start both VMs
    $ipv4 = Start-VMandGetIP $VMName $HvServer $VMPort $VMRootUser $VMPassword
    $vm2ipv4 = Start-VMandGetIP $VM2Name $DependencyVmHost $VMPort $VMRootUser $VMPassword

    # Set SSH key for both VMs
    # Setup ssh on VM1
    Copy-RemoteFiles -uploadTo $ipv4 -port $VMPort -files `
        ".\Testscripts\Linux\enablePasswordLessRoot.sh,.\Testscripts\Linux\utils.sh,.\Testscripts\Linux\SR-IOV-Utils.sh" `
        -username $VMRootUser -password $VMPassword -upload
    Copy-RemoteFiles -uploadTo $vm2ipv4 -port $VMPort -files `
        ".\Testscripts\Linux\enablePasswordLessRoot.sh,.\Testscripts\Linux\utils.sh,.\Testscripts\Linux\SR-IOV-Utils.sh" `
        -username $VMRootUser -password $VMPassword -upload
    Run-LinuxCmd -ip $ipv4 -port $VMPort -username $VMRootUser -password `
        $VMPassword -command "chmod +x ~/*.sh"
    Run-LinuxCmd -ip $vm2ipv4 -port $VMPort -username $VMRootUser -password `
        $VMPassword -command "chmod +x ~/*.sh"
    Run-LinuxCmd -ip $ipv4 -port $VMPort -username $VMRootUser -password `
        $VMPassword -command "./enablePasswordLessRoot.sh ; cp -rf /root/.ssh /home/$VMUsername"

    # Copy keys from VM1 and setup VM2
    Copy-RemoteFiles -download -downloadFrom $ipv4 -port $VMPort -files `
        "/root/sshFix.tar" -username $VMRootUser -password $VMPassword -downloadTo $LogDir
    Copy-RemoteFiles -uploadTo $vm2ipv4 -port $VMPort -files "$LogDir\sshFix.tar" `
        -username $VMRootUser -password $VMPassword -upload
    Run-LinuxCmd -ip $vm2ipv4 -port $VMPort -username $VMRootUser -password `
            $VMPassword -command "./enablePasswordLessRoot.sh ; cp -rf /root/.ssh /home/$VMUsername"

    # Construct and send sriov_constants.sh
    Remove-Item sriov_constants.sh -Force -EA SilentlyContinue
    "SSH_PRIVATE_KEY=id_rsa" | Out-File sriov_constants.sh
    "NETMASK=${netmask}" | Out-File sriov_constants.sh -Append
    [array]::Sort($vfIP)
    for ($i=0; $i -lt $vfIterator; $i++){
        # get ip from array
        $j = $i + 1
        if ($maxNICs -eq "yes") {
            $ipToSend = "10.1${nicIterator}.12.${j}"
            if ($j % 2 -eq 0) {
                $nicIterator++
            }
        }
        else {
            $ipToSend = $vfIP[$i]
        }
        Write-LogInfo "Will append VF_IP$j=$ipToSend to sriov_constants.sh"
        "VF_IP$j=$ipToSend" | Out-File sriov_constants.sh -Append
    }

    # Configure VF on both VMs
    Set-VFInGuest $VMRootUser $ipv4 $VMPassword $VMPort $VMName "1" $vfIP1
    if (-not $?) {
        Write-LogErr "Failed to configure VF on $VMName"
        return $False
    }
    Set-VFInGuest $VMRootUser $vm2ipv4 $VMPassword $VMPort $VM2Name "2" $vfIP2
    if (-not $?) {
        Write-LogErr "Failed to configure VF on $VM2Name"
        return $False
    }
    return $True
}

Main -VMName $AllVMData.RoleName -hvServer $xmlConfig.config.Hyperv.Hosts.ChildNodes[0].ServerName `
    -VMPort $AllVMData.SSHPort -VMUserName $user -VMPassword $password -TestParams $TestParams
