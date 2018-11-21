# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

param([string] $TestParams)

function Main {
    param (
        $VMName,
        $HvServer,
        $Ipv4,
        $VMPort,
        $VMUserName,
        $VMPassword,
        $RootDir,
        $TestParams,
        $TestPlatform
    )
    
    $nmi = $null
    $useNFS = $null

    if (-not $TestParams) {
        LogErr "No test parameters specified"
        return "Aborted"
    }
    if (-not $RootDir) {
        LogMsg "Warn: no rootdir was specified"
    } else {
        Set-Location $RootDir
    }

    # Parse test parameters
    $params = $testParams.Split(";")
    foreach ($p in $params) {
        $fields = $p.Split("=")

        switch ($fields[0].Trim()) {
          "crashkernel"   { $crashKernel    = $fields[1].Trim() }
          "NMI"           { $nmi = $fields[1].Trim() }
          "VM2NAME"       { $vm2Name = $fields[1].Trim() }
          "use_nfs"       { $useNFS = $fields[1].Trim() }
          "VCPU"          { $vCPU = $fields[1].Trim() }
          default         {}
        }
    }

    if (-not $crashKernel) {
        LogErr "Test parameter crashkernel was not specified"
        return "FAIL"
    }

    if ($TestPlatform -eq "HyperV") { 
        $buildNumber = Get-HostBuildNumber $HvServer
        #$RHEL7_Above = Get-VMFeatureSupportStatus -Ipv4 $Ipv4 -SSHPort $VMPort `
        #    -Username $VMUserName -Password $VMPassword -SupportKernel "3.10.0-123"
        $RHEL7_Above = $True
        # WS2012 does not support Debug-VM NMI injection, skipping
        if ( ($buildNumber -le "9200") -and ($nmi -eq 1) ) {
            LogErr "WS2012 does not support Debug-VM NMI injection"
            return "FAIL"
        }
        # Confirm the second VM and NFS
        if ($vm2Name -and $useNFS -eq "yes") {
            $checkState = Get-VM -Name $vm2Name -ComputerName $HvServer

            if ($checkState.State -notlike "Running") {
                Start-VM -Name $vm2Name -ComputerName $HvServer
                if (-not $LASTEXITCODE) {
                    LogErr "Unable to start VM ${vm2Name}"
                    return "FAIL"
                }
                LogMsg "Succesfully started dependency VM ${vm2Name}"
            }

            $newIP = Get-IPv4AndWaitForSSHStart -VMName $VMName -HvServer $HvServer `
                -VmPort $VmPort -User $VMUserName -Password $VMPassword -StepTimeout 360
            if ($newIP) {
                $vm2ipv4 = $newIP
            } else {
                LogErr "Failed to boot up NFS Server $vm2Name"
                return "FAIL"
            }

            $retVal = RunLinuxCmd -username $VMUserName -password $VMPassword -ip $Ipv4 -port $VMPort `
                -command "echo 'vm2ipv4=${vm2ipv4}' >> ~/constants.sh"
            if ($retVal -eq $false) {
                LogErr "Failed to echo ${vm2ipv4} to constants.sh"
                return "FAIL"
            }

            $retVal = RunLinuxCmd -username $VMUserName -password $VMPassword -ip $Ipv4 -port $VMPort `
                -command "chmod u+x KDUMP-NFSConfig.sh && ./KDUMP-NFSConfig.sh"
            if ($retVal -eq $false) {
                LogErr "Failed to configure the NFS server!"
                return "FAIL"
            }
        }
        # Append host build number to constants.sh
        $retVal = RunLinuxCmd -username $VMUserName -password $VMPassword -ip $Ipv4 -port $VMPort `
                -command "echo BuildNumber=$BuildNumber >> ./constants.sh"
    }

    # Configure kdump on the VM
    $retVal = RunLinuxCmd -username $VMUserName -password $VMPassword -ip $Ipv4 -port $VMPort `
        -command "export HOME=``pwd``;chmod u+x KDUMP-Config.sh && ./KDUMP-Config.sh" -runAsSudo

    # Rebooting the VM in order to apply the kdump settings
    .\Tools\plink.exe -C -pw $VMPassword -P $VMPort root@$Ipv4 "reboot"
    LogMsg "Rebooting VM $VMName after kdump configuration..."
    Start-Sleep 10 # Wait for kvp & ssh services stop

    # Wait for VM boot up and update ip address
    Wait-ForVMToStartSSH -Ipv4addr $Ipv4 -StepTimeout 360

    # Prepare the kdump related
    $retVal = RunLinuxCmd -username $VMUserName -password $VMPassword -ip $Ipv4 -port $VMPort `
                -command "export HOME=``pwd``;chmod u+x KDUMP-Execute.sh && ./KDUMP-Execute.sh" -runAsSudo

    # Trigger the kernel panic
    LogMsg "Trigger the kernel panic..."
    if ($nmi -eq 1) {
        # Waiting to kdump_execute.sh to finish execution.
        Start-Sleep -S 100
        Debug-VM -Name $VMName -InjectNonMaskableInterrupt -ComputerName $HvServer -Force
    } else {
        if ($vcpu -eq 4){
            LogMsg "Kdump will be triggered on VCPU 3 of 4"
            $retVal = RunLinuxCmd -username $VMUserName -password $VMPassword -ip $Ipv4 -port $VMPort `
                -command "taskset -c 2 echo c > /proc/sysrq-trigger"
        } else {
            # If directly use plink to trigger kdump, command fails to exit, so use start-process
            RunLinuxCmd -username "root" -password $VMPassword -ip $Ipv4 -port $VMPort `
                -command "echo c > /proc/sysrq-trigger" -RunInBackGround
        }
    }

    # Give the host a few seconds to record the event
    LogMsg "Waiting seconds to record the event..."
    Start-Sleep 10

    if ($TestPlatform -eq "HyperV") {
        if ((-not $RHEL7_Above) -and ($BuildNumber -eq "14393")){
            Start-Sleep 120 # Make sure dump completed
            Stop-VM -VMName $VMName -ComputerName $HvServer -TurnOff -Force
            Start-VM -VMName $VMName -ComputerName $HvServer
        }
    }

    # Wait for VM boot up and update ip address
    Wait-ForVMToStartSSH -Ipv4addr $Ipv4 -StepTimeout 600

    # Verifying if the kernel panic process creates a vmcore file of size 10M+
    $retVal = RunLinuxCmd -username $VMUserName -password $VMPassword -ip $Ipv4 -port $VMPort `
                -command "export HOME=``pwd``;chmod u+x KDUMP-Results.sh && ./KDUMP-Results.sh $vm2ipv4" -runAsSudo
    if (-not $retVal) {
        LogErr "Results are not as expected. Check logs for details."

        # Stop NFS server VM
        if ($vm2Name) {
            Stop-VM -VMName $vm2Name -ComputerName $HvServer -Force
        }
        return "FAIL"
    }
    $result = RunLinuxCmd -username "root" -password $VMPassword -ip $Ipv4 -port $VMPort `
                -command "find /var/crash/ -name vmcore -type f -size +10M" -runAsSudo
    LogMsg "Files found: $result"
    LogMsg "Test passed: crash file $result is present"

    # Stop NFS server VM
    if ($vm2Name) {
        Stop-VM -VMName $vm2Name -ComputerName $HvServer -Force
    }

    return "PASS"
}


Main -VMName $AllVMData.RoleName -HvServer $xmlConfig.config.Hyperv.Hosts.ChildNodes[0].ServerName `
         -ipv4 $AllVMData.PublicIP -VMPort $AllVMData.SSHPort `
         -VMUserName $user -VMPassword $password -rootDir $WorkingDirectory `
         -testParams $testParams -TestPlatform $XmlConfig.config.CurrentTestPlatform
