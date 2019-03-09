# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Synopsis
    Hot Add a NIC to a Gen2 VM that booted without a NIC.

.Description
    Test case for booting a Gen2 VM without a NIC, hot add a
    NIC, verify it works, then hot remove the NIC.
#>
param([String] $TestParams,
      [object] $AllVmData)
function Main {
    param (
        $VMName,
        $HvServer,
        $Ipv4,
        $VMPort,
        $VMUserName,
        $VMPassword,
        $RootDir
    )

    $KVP_KEY = "HotAddTest"
    $Switch_Name = "External"

    # Change the working directory to where we should be
    Set-Location $RootDir

    # Verify the target VM is a Gen2 VM
    $vm = Get-VM -Name $VMName -ComputerName $HvServer -ErrorAction SilentlyContinue
    if ($vm.Generation -ne 2) {
        Write-LogWarn "This test requires a Gen2 VM."
        return "SKIPPED"
    }

    # Verify Windows Server version
    $osInfo = Get-HostBuildNumber $HvServer
    if (-not $osInfo) {
        Write-LogErr "Unable to collect Operating System information"
        return "FAIL"
    }
    if ($osInfo -le 9600) {
        Write-LogWarn "This test requires Windows Server 2016 or higher"
        return "ABORTED"
    }

    # Verify the target VM has a single NIC - Standard LISA test configuration
    Write-LogInfo "Verify the VM has a single NIC"
    $nics = Get-VMNetworkAdapter -VMName $VMName -ComputerName $HvServer -ErrorAction SilentlyContinue
    if (-not $?) {
        Write-LogErr "VM '${VMName}' does not have a single NIC"
        return "ABORTED"
    }

    if ($nics.Length -ne 1) {
        Write-LogErr "VM '${VMName}' has more than one NIC"
        return "ABORTED"
    }

    # Configure the NET-Verify-Boot-NoNIC.sh script to be run automatically
    # on boot
    $linuxRelease = Detect-LinuxDistro
    if ($linuxRelease -eq "CENTOS" -or $linuxRelease -eq "FEDORA" -or $linuxRelease -eq "REDHAT") {
        Run-LinuxCmd -Command "echo '${VMPassword}' | sudo -S -s eval `"export HOME=``pwd``;chmod +x /etc/rc.d/rc.local`"" `
            -Username $VMUserName -password $VMPassword -ip $Ipv4 -port $VMPort `
            -runMaxAllowedTime $Timeout
        Run-LinuxCmd -Command "echo '${VMPassword}' | sudo -S -s eval `"export HOME=``pwd``;echo 'chmod 755 /home/$VMUserName/NET-Verify-Boot-NoNIC.sh' >> /etc/rc.d/rc.local`"" `
            -Username $VMUserName -password $VMPassword -ip $Ipv4 -port $VMPort `
            -runMaxAllowedTime $Timeout
        Run-LinuxCmd -Command "echo '${VMPassword}' | sudo -S -s eval `"export HOME=``pwd``;echo 'cd /home/$VMUserName && ./NET-Verify-Boot-NoNIC.sh > /home/$VMUserName/NET-Verify-Boot-NoNIC.log  &' >> /etc/rc.d/rc.local`"" `
            -Username $VMUserName -password $VMPassword -ip $Ipv4 -port $VMPort `
            -runMaxAllowedTime $Timeout
    }
    elseif ($linuxRelease -eq "UBUNTU" -or $linuxRelease -eq "DEBIAN") {
        Run-LinuxCmd -Command "echo '${VMPassword}' | sudo -S -s eval `"export HOME=``pwd``;systemctl start cron.service`"" `
            -Username $VMUserName -password $VMPassword -ip $Ipv4 -port $VMPort `
            -runMaxAllowedTime $Timeout
        Run-LinuxCmd -Command "echo '${VMPassword}' | sudo -S -s eval `"export HOME=``pwd``;echo '@reboot chmod 755 /home/$VMUserName/NET-Verify-Boot-NoNIC.sh' >> /var/spool/cron/crontabs/root`"" `
            -Username $VMUserName -password $VMPassword -ip $Ipv4 -port $VMPort `
            -runMaxAllowedTime $Timeout
        Run-LinuxCmd -Command "echo '${VMPassword}' | sudo -S -s eval `"export HOME=``pwd``;echo '@reboot cd /home/$VMUserName && ./NET-Verify-Boot-NoNIC.sh > /home/$VMUserName/NET-Verify-Boot-NoNIC.log  &' >> /var/spool/cron/crontabs/root`"" `
            -Username $VMUserName -password $VMPassword -ip $Ipv4 -port $VMPort `
            -runMaxAllowedTime $Timeout
        Run-LinuxCmd -Command "echo '${VMPassword}' | sudo -S -s eval `"export HOME=``pwd``;chmod 0600 /var/spool/cron/crontabs/root`"" `
            -Username $VMUserName -password $VMPassword -ip $Ipv4 -port $VMPort `
            -runMaxAllowedTime $Timeout
    }
    elseif ($linuxRelease -eq "SLES") {
        $cmdToVM = @"
[Unit]
ConditionFileIsExecutable=/home/$VMUserName/NET-Verify-Boot-NoNIC.sh
After=getty.target

[Service]
Type=idle
ExecStart= cd /home/$VMUserName && ./NET-Verify-Boot-NoNIC.sh
TimeoutSec=0
RemainAfterExit=yes
"@

        Run-LinuxCmd -Command "echo '${VMPassword}' | sudo -S -s eval `"export HOME=``pwd``;echo '$cmdToVM' > /etc/systemd/system/after-local.service`"" `
            -Username $VMUserName -password $VMPassword -ip $Ipv4 -port $VMPort `
            -runMaxAllowedTime $Timeout
        Run-LinuxCmd -Command "echo '${VMPassword}' | sudo -S -s eval `"export HOME=``pwd``;chmod +x /etc/systemd/system/after-local.service`"" `
            -Username $VMUserName -password $VMPassword -ip $Ipv4 -port $VMPort `
            -runMaxAllowedTime $Timeout
        Run-LinuxCmd -Command "echo '${VMPassword}' | sudo -S -s eval `"export HOME=``pwd``;chmod 755 /home/$VMUserName/NET-Verify-Boot-NoNIC.sh`"" `
            -Username $VMUserName -password $VMPassword -ip $Ipv4 -port $VMPort `
            -runMaxAllowedTime $Timeout
        Run-LinuxCmd -Command "echo '${VMPassword}' | sudo -S -s eval `"export HOME=``pwd``;systemctl daemon-reload && systemctl enable after-local.service`"" `
            -Username $VMUserName -password $VMPassword -ip $Ipv4 -port $VMPort `
            -runMaxAllowedTime $Timeout
    }
    else {
        Write-LogErr "Unsupported linux distribution '${linuxRelease}'"
        return "ABORTED"
    }

    # Stop the VM
    Write-LogInfo "Stopping the VM..."
    Stop-VM -Name "${VMName}" -ComputerName $HvServer -Force -ErrorAction SilentlyContinue
    if (-not $?) {
        Write-LogErr "Unable to stop VM to allow removal of original NIC"
        return "FAIL"
    }

    # Remove the original NIC
    Write-LogInfo "Removing the original NIC from the VM..."
    Remove-VMNetworkAdapter -VMName $VMName -ComputerName $HvServer -ErrorAction SilentlyContinue
    if (-not $?) {
        Write-LogErr "Unable to Remove the original NIC"
        return "FAIL"
    }

    Write-LogInfo "Verifying the VM does not have any NICs..."
    $nics = Get-VMNetworkAdapter -VMName $VMName -Name "${nicName}" -ComputerName $HvServer -ErrorAction SilentlyContinue
    if (-not $?) {
        Write-LogErr "VM '${VMName}' still has a NIC after Hot Remove"
        return "FAIL"
    }

    # Boot the VM
    Write-LogInfo "Starting the VM..."
    Start-VM -Name "${VMName}" -ComputerName $HvServer -ErrorAction SilentlyContinue
    if (-not $?) {
        Write-LogErr "Unable to start VM after removing original NIC"
        return "FAIL"
    }

    #    This code runs in lock step with the KVP_VerifyBootNoNIC.sh script,
    #    which is running on the Linux VM. KVP values are used to keep this
    #    script in sync with the Bash script on the VM.
    #
    #    Wait for the Bash script to create the HotAddTest KVP item.
    #    Verify it is set to "NoNICs'
    #    Hot add a NIC
    #    Wait for the Bash script to modify the HotAddTest KVP value to 'NICUp'
    #    Verify Hyper-V sees the IP addresses assigned to the hot added NIC.
    #    Hot remove the NIC
    #    Wait for the Bash script to modify the HotAddTest KVP value to 'NoNICs'
    #
    Write-LogInfo "Waiting for the VM to create the HotAddTest KVP item"
    $tmo = 400
    $value = $null
    while ($tmo -gt 0) {
        $value = Get-KvpItem $VMName $HvServer ${KVP_KEY}
        Write-LogInfo "Trying to get KVP Item value..."
        if ($value -ne $null) {
            break
        }

        $tmo -= 60
        Start-Sleep -Seconds 60
    }

    if ($value -ne "NoNICs") {
        Write-LogErr "The VM never reported 0 NICs found."
        return "FAIL"
    }

    # Hot Add a NIC
    Write-LogInfo "Hot add a synthetic NIC"
    Add-VMNetworkAdapter -VMName $VMName -SwitchName $Switch_Name -ComputerName $HvServer -ErrorAction SilentlyContinue
    if (-not $?) {
        Write-LogErr "Unable to Hot Add NIC to VM '${VMName}' on server '${HvServer}'"
        return "FAIL"
    }

    # Wait for the guest to modify the HotAddTest KVP item value to 'NICUp'
    Write-LogInfo "Waiting for the VM to set the HotAddTest KVP item to NICUp"
    $tmo = 1000
    $value = $null
    while ($tmo -gt 0) {
        $value = Get-KVPItem $VMName $HvServer ${KVP_KEY}
        Write-LogInfo "Trying to get KVP Item value..."
        if ($value -eq "NICUp") {
            break
        }

        $tmo -= 10
        Start-Sleep -Seconds 10
    }

    if ($value -ne "NICUp") {
        Write-LogErr "The VM never reported the NIC is up"
        return "FAIL"
    }

    # Verify the Hot Added NIC was assigned an IP address
    $nic = Get-VMNetworkAdapter -VMName $VMName -ComputerName $HvServer -ErrorAction SilentlyContinue
    if (-not $nic) {
        Write-LogErr "Unable to create Network Adapter object for VM '${VMName}'"
        return "FAIL"
    }

    if ($nic.IPAddresses.length -lt 2) {
        Write-LogErr "Insufficient IP addresses reported by test VM"
        return "FAIL"
    }

    # Hot Remove the NIC
    Remove-VMNetworkAdapter -VMName $VMName -Name "${nicName}" -ComputerName $HvServer -ErrorAction SilentlyContinue
    if (-not $?) {
        Write-LogErr "Unable to remove hot added NIC"
        return "FAIL"
    }

    # Wait for the guest to modify the HotAddTest KVP item value to 'NoNICs'
    Write-LogInfo "Waiting for the VM to set the HotAddTest KVP item to 'NoNICs'"
    $tmo = 300
    $value = $null
    while ($tmo -gt 0) {
        $value = Get-KVPItem $VMName $HvServer "${KVP_KEY}"
        if ($value -eq "NoNICs") {
            break
        }

        $tmo -= 10
        Start-Sleep -Seconds 10
    }

    if ($value -ne "NoNICs") {
        Write-LogErr "The VM never detected the Hot Remove of the NIC"
        return "FAIL"
    }
    else {
        Write-LogInfo "The VM detected the Hot Remove of the NIC"
        return "PASS"
    }
}

Main -VMName $AllVMData.RoleName -HvServer $GlobalConfig.Global.Hyperv.Hosts.ChildNodes[0].ServerName `
    -Ipv4 $AllVMData.PublicIP -VMPort $AllVMData.SSHPort `
    -VMUserName $user -VMPassword $password -RootDir $WorkingDirectory