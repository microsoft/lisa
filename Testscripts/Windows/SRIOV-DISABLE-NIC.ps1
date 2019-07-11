# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Synopsis
    Disable/Enable NIC on host (using disable/enable-netAdapter) and
    get the VF count inside the VM.

.Description
    Get the throughput before disabling the NIC. Disable NIC and get the
    VF count inside the VM (it sohuld be 0). Enable NIC again and get the
    throughput. Finally, compare the initial throughput and the final one -
    they should be comparable.
#>

param ([string] $TestParams, [object] $AllVMData)

function Main {
    param (
        $VMUsername,
        $VMName,
        $HvServer,
        $VMPort,
        $VMPassword
    )
    $moduleCheckCMD = "lspci -vvv | grep -c 'mlx[4-5]_core\|mlx4_en\|ixgbevf'"
    $vfCheckCMD = "find /sys/devices -name net -a -ipath '*vmbus*' | grep -c pci"
    try {
        # Get IP
        $ipv4 = Get-IPv4ViaKVP $VMName $HvServer
        $vm2ipv4 = Get-IPv4ViaKVP $DependencyVmName $DependencyVmHost

        # Start client on dependency VM
        Run-LinuxCmd -ip $vm2ipv4 -port $VMPort -username $VMUsername -password `
            $VMPassword -command "iperf3 -s > client.out" -RunInBackGround
        Start-Sleep -s 5

        # Run iPerf on client side for 30 seconds with SR-IOV enabled
        Run-LinuxCmd -ip $ipv4 -port $VMPort -username $VMUsername -password `
            $VMPassword -command "source sriov_constants.sh ; iperf3 -t 30 -c `$VF_IP2 --logfile PerfResults.log"

        [decimal]$vfEnabledThroughput = Run-LinuxCmd -ip $ipv4 -port $VMPort -username $VMUsername -password `
            $VMPassword -command "tail -4 PerfResults.log | head -1 | awk '{print `$7}'" `
            -ignoreLinuxExitCode:$true
        if (-not $vfEnabledThroughput){
            Write-LogErr "No result was logged! Check if iPerf was executed!"
            return "FAIL"
        }
        Write-LogInfo "The throughput before disabling NIC is $vfEnabledThroughput Gbits/sec"

        # Disable SR-IOV on test VM
        $switchName = Get-VMNetworkAdapter -VMName $VMName -ComputerName $HvServer | `
            Where-Object {$_.SwitchName -like 'SRIOV*'} | Select-Object -ExpandProperty SwitchName
        $hostNICName = Get-VMSwitch -Name $switchName -ComputerName $HvServer | `
            Select-Object -ExpandProperty NetAdapterInterfaceDescription
        Write-LogInfo "Disabling $hostNICName"
        Disable-NetAdapter -InterfaceDescription $hostNICName -CIMsession $HvServer -Confirm:$False | Out-Null
        if (-not $?) {
            Write-LogErr "Failed to disable $hostNICName!"
            return "FAIL"
        }
        # Wait 1 minute to make sure VF has changed. It is an expected behavior
        Write-LogInfo "Wait 1 minute for VF to be put down"
        Start-Sleep -s 60

        # Check if the SR-IOV module is still loaded
        $moduleCount = Run-LinuxCmd -ip $ipv4 -port $VMPort -username $VMUsername -password `
            $VMPassword -command $moduleCheckCMD -ignoreLinuxExitCode:$true
        if ($moduleCount -gt 0) {
            Write-LogErr "Module is still loaded"
            return "FAIL"
        }
        # Check if the VF is still present
        $vfCount = Run-LinuxCmd -ip $ipv4 -port $VMPort -username $VMUsername -password `
            $VMPassword -command $vfCheckCMD -ignoreLinuxExitCode:$true
        if ($vfCount -gt 0) {
            Write-LogErr "VF is still present"
            return "FAIL"
        }

        # Enable SR-IOV on test VM
        Write-LogInfo "Enable VF on on $hostNICName"
        Enable-NetAdapter -InterfaceDescription $hostNICName -CIMsession $HvServer -Confirm:$False | Out-Null
        if (-not $?) {
            Write-LogErr "Failed to enable $hostNIC_name! Please try to manually enable it"
            return "FAIL"
        }
        # Wait 1 minute to make sure VF has changed. It is an expected behavior
        Write-LogInfo "Wait 1 minute for VF to be put up"
        Start-Sleep -s 60
        # Read the throughput again, it should be higher than before
        Run-LinuxCmd -ip $ipv4 -port $VMPort -username $VMUsername -password `
            $VMPassword -command "source sriov_constants.sh ; iperf3 -t 30 -c `$VF_IP2 --logfile PerfResults.log"
        [decimal]$vfEnabledThroughput  = $vfEnabledThroughput * 0.7
        [decimal]$vfFinalThroughput = Run-LinuxCmd -ip $ipv4 -port $VMPort -username $VMUsername -password `
            $VMPassword -command "tail -4 PerfResults.log | head -1 | awk '{print `$7}'" `
            -ignoreLinuxExitCode:$true
        Write-LogInfo "The throughput after re-enabling NIC is $vfFinalThroughput Gbits/sec"
        if ($vfEnabledThroughput -gt $vfFinalThroughput) {
            Write-LogErr "After re-enabling NIC, the throughput has not increased enough"
            return "FAIL"
        }

        return "PASS"
    } catch {
        $ErrorMessage = $_.Exception.Message
        $ErrorLine = $_.InvocationInfo.ScriptLineNumber
        Write-LogErr "$ErrorMessage at line: $ErrorLine"
        return "Aborted"
    } finally {
        # Enable SR-IOV on test VM
        if ($hostNICName){
            Enable-NetAdapter -InterfaceDescription $hostNICName -CIMsession $hvServer -Confirm:$False | Out-Null
        }
    }
}

Main -VMName $AllVMData.RoleName -hvServer $GlobalConfig.Global.Hyperv.Hosts.ChildNodes[0].ServerName `
    -VMPort $AllVMData.SSHPort -VMUsername $user -VMPassword $password
