# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Description
    Test LIS and shutdown with multiple CPUs
#>

param([String] $TestParams)

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

    # Default to 64 cores for a generic VM
    $guestMaxCPUs = 64
    $vCPU = $null

    # Change the working directory for the log files
    if (-not (Test-Path $rootDir)) {
        LogErr "Error: The directory `"${rootDir}`" does not exist"
        return "FAIL"
    }
    Set-Location $rootDir

    $OSInfo = Get-WmiObject -Class Win32_OperatingSystem -ComputerName $HvServer
    if ($OSInfo) {
        if ($OSInfo.Caption -match '.2008 R2.') {
            $guestMaxCPUs = 4
        } else {
            # Check VM OS architecture and set max CPU allowed
            $linuxArch = RunLinuxCmd -username "root" -password $VMPassword -ip `
                            $Ipv4 -port $VMPort -command "uname -m"
            if ($linuxArch -eq "i686") {
                $guestMaxCPUs = 32
            }
            if ($linuxArch -eq "x86_64") {
                $guestMaxCPUs = 64
            }

            if ((Get-VMGeneration $VMName $HvServer) -eq "2" ) {
                $guestMaxCPUs = 240
            }
        }

        # Get the total number of Logical processors
        $maxCPUs =  Get-WmiObject -Class Win32_ComputerSystem -ComputerName $HvServer | `
                    Select-Object -ExpandProperty "NumberOfLogicalProcessors"
        if ($guestMaxCPUs -gt $maxCPUs) {
            LogMsg "VM maximum cores is limited by the number of Logical cores: $maxCPUs"
            $guestMaxCPUs = $maxCPUs
        }
    }

    # Shutdown VM in order to change the cores count
    try {
        Stop-VM -Name $VMName -ComputerName $HvServer
    } catch [system.exception] {
        LogErr "Error: Unable to stop VM $VMName!"
        return "FAIL"
    }

    try {
        Wait-ForVMToStop $VMName $HvServer 200
    } catch [system.exception] {
        LogErr "Error: Timed out while stopping VM $VMName!"
        return "FAIL"
    }

    Set-VM -Name $VMName -ComputerName $HvServer -ProcessorCount $guestMaxCPUs
    if ($? -eq "True") {
        LogMsg "CPU cores count updated to $guestMaxCPUs"
    } else {
        LogErr "Error: Unable to update CPU count to $guestMaxCPUs!"
        return "FAIL"
    }

    # Start VM and wait for SSH access
    Start-VM -Name $VMName -ComputerName $HvServer
    $newIpv4 = Get-Ipv4AndWaitForSSHStart $VMName $HvServer $VMPort $VMUserName `
                $VMPassword 300
    if ($newIpv4) {
        # In some cases the IP changes after a reboot
        Set-Variable -Name "Ipv4" -Value $newIpv4
    } else {
        LogErr "Error: VM $VMName failed to start after setting $guestMaxCPUs vCPUs"
        return "FAIL"
    }

    # Determine how many cores the VM has detected
    $vCPU = RunLinuxCmd -username "root" -password $VMPassword -ip $Ipv4 -port $VMPort `
            -command "cat /proc/cpuinfo | grep processor | wc -l"
    if ($vCPU -eq $guestMaxCPUs) {
        LogMsg "CPU count inside VM is $guestMaxCPUs"
        LogMsg "VM $VMName successfully started with $guestMaxCPUs cores."
        return "PASS"
    } else {
        LogErr "Error: Wrong vCPU count of $vCPU detected on the VM, expected $guestMaxCPUs!"
        return "FAIL"
    }
}

Main -VMName $AllVMData.RoleName -hvServer $xmlConfig.config.Hyperv.Hosts.ChildNodes[0].ServerName `
         -Ipv4 $AllVMData.PublicIP -VMPort $AllVMData.SSHPort `
         -VMUserName $user -VMPassword $password -RootDir $WorkingDirectory