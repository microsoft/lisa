# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
<#
.Synopsis
    This script tests hyper-v daemons service status and files.

.Description
    The script will enable "Guest services" in "Integration Service" if it
    is disabled, then execute "Hyperv_Daemons_Files_Status" to check hypervkvpd,
    hypervvssd,hypervfcopyd status and default files.
'
#>


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

    $gsi = $null
    $remoteScript = "LIS-Check-HypervDaemons-Files-Status.sh"
    #######################################################################
    #
    #	Main body script
    #
    #######################################################################

    # Checking the input arguments
    if (-not $VMName) {
        LogErr  "VM name is null!"
        return "FAIL"
    }

    if (-not $HvServer) {
        LogErr "hvServer is null!"
        return "FAIL"
    }
    #
    # Change the working directory for the log files
    # Delete any previous summary.log file, then create a new one
    #
    if (-not (Test-Path $RootDir)) {
        LogErr "The directory `"$RootDir}`" does not exist"
        return "FAIL"
    }
    Set-Location $RootDir
    # get host build number
    $BuildNumber = Get-HostBuildNumber -hvServer $HvServer

    if ($BuildNumber -eq 0) {
        return "FAIL"
    }
    # if lower than 9600, skip "Guest Service Interface" check
    if ($BuildNumber -ge 9600) {
        #
        # Verify if the Guest services are enabled for this VM
        #
        $gsi = Get-VMIntegrationService -vmName $VMName -ComputerName $HvServer -Name "Guest Service Interface"
        if (-not $gsi) {
            LogErr "Unable to retrieve Integration Service status from VM '${VMName}'"
            return "FAIL"
        }

        if (-not $gsi.Enabled) {
            LogWarn "The Guest services are not enabled for VM '${VMName}'"
            if ((Get-VM -ComputerName $HvServer -Name $VMName).State -ne "Off") {
                Stop-VM -ComputerName $HvServer -Name $VMName -Force -Confirm:$False
            }

            # Waiting until the VM is off
            LogMsg "Turning off VM:'${VMname}'"
            while ((Get-VM -ComputerName $HvServer -Name $VMName).State -ne "Off") {
                Start-Sleep -Seconds 5
            }
            LogMsg "Enabling  Guest services on VM:'${VMname}'"
            Enable-VMIntegrationService -Name "Guest Service Interface" -vmName $VMName -ComputerName $HvServer
            LogMsg "Starting VM:'${VMname}'"
            Start-VM -Name $VMName -ComputerName $HvServer

            LogMsg "Waiting for the VM to run again and respond to SSH - port"
            if (-not (Wait-ForVMToStartSSH -Ipv4addr $Ipv4 -StepTimeout 200)) {
                LogErr  "Test case timed out for VM to be running again!"
                return "FAIL"
            }
        }
    }
    #
    # Run the guest VM side script to verify floppy disk operations
    #
    $stateFile = "${LogDir}\state.txt"
    $Hypervcheck = "echo '${VMPassword}' | sudo -S -s eval `"export HOME=``pwd``;bash ${remoteScript} > Hypervcheck.log`""
    RunLinuxCmd -username $VMUserName -password $VMPassword -ip $Ipv4 -port $VMPort $Hypervcheck -runAsSudo
    RemoteCopy -download -downloadFrom $Ipv4 -files "/home/${VMUserName}/state.txt" `
        -downloadTo $LogDir -port $VMPort -username $VMUserName -password $VMPassword
    RemoteCopy -download -downloadFrom $Ipv4 -files "/home/${VMUserName}/Hypervcheck.log" `
        -downloadTo $LogDir -port $VMPort -username $VMUserName -password $VMPassword
    $contents = Get-Content -Path $stateFile
    if (($contents -eq "TestAborted") -or ($contents -eq "TestFailed")) {
        LogErr "Error: Running $remoteScript script failed on VM!"
        return "FAIL"
    }
}
Main -VMName $AllVMData.RoleName -HvServer $xmlConfig.config.Hyperv.Hosts.ChildNodes[0].ServerName `
    -Ipv4 $AllVMData.PublicIP -VMPort $AllVMData.SSHPort `
    -VMUserName $user -VMPassword $password -RootDir $WorkingDirectory