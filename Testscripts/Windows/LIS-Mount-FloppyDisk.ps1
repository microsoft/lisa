# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.


<#
.Synopsis
    Mount a floppy vfd file in the VMs floppy drive.

.Description
    Mount a floppy in the VMs floppy drive
    The .vfd file that will be mounted in the floppy drive
    is named <vmName>.vfd.  If the virtual floppy does not
    exist, it will be created.

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

    $vfdPath = "$null"
    $remoteScript = "LIS-Mount-FloppyDisk.sh"
    #############################################################
    #
    # Main script body
    #
    #############################################################
    # Change the working directory to where we need to be
    if (-not (Test-Path $RootDir)) {
        LogErr "Error: The directory `"${RootDir}`" does not exist!"
        return "FAIL"
    }
    Set-Location $RootDir
    # Collect Hyper-v settings info
    $hostInfo = Get-VMHost -ComputerName $HvServer
    if (-not $hostInfo) {
        LogErr "Unable to collect Hyper-V settings for ${HvServer}"
        return "FAIL"
    }

    # Check for floppy support. If it's not present, test will be skipped

    $sts = RunLinuxCmd -username $VMUserName -password $VMPassword -ip $Ipv4 -port $VMPort -command "cat /boot/config-`$(uname -r) | grep -e CONFIG_BLK_DEV_FD=y -e CONFIG_BLK_DEV_FD=m" -runAsSudo
    if (-not $?) {
        LogWarn "Support for floppy does not exist! Test skipped!"
        return "Aborted"
    }

    # Skip test for generation 2 VM

    $vmGeneration = Get-VMGeneration -vmName $VMName -hvServer $HvServer
    if ( $vmGeneration -eq 2 ) {
        LogMsg "Generation 2 VM does not support floppy disks."
        return "Aborted"
    }

    $defaultVhdPath = $hostInfo.VirtualHardDiskPath
    if (-not $defaultVhdPath.EndsWith("\")) {
        $defaultVhdPath += "\"
    }

    $vfdPath = "${defaultVhdPath}${vmName}.vfd"

    $fileInfo = Get-RemoteFileInfo -filename $vfdPath  -server $HvServer
    if (-not $fileInfo) {
    #
    # The .vfd file does not exist, so create one
    #
        $newVfd = New-VFD -Path $vfdPath -ComputerName $HvServer
        if (-not $newVfd) {
            LogErr "Unable to create VFD file ${vfdPath}"
            return "FAIL"
        }
    }
    else {
        LogMSg "Info: The file ${vfdPath} already exists"
    }
    #
    # Add the vfd
    #
    Set-VMFloppyDiskDrive -Path $vfdPath -VMName $VMName -ComputerName $HvServer
    if ($? -eq "True") {
        LogMsg "Mounted the floppy file!"
    }
    else {
        LogErr "Unable to mount the floppy file!"
        return "FAIL"
    }
    #
    # Run the guest VM side script to verify floppy disk operations
    #
    $stateFile = "${LogDir}\state.txt"
    $MountFloppy = "echo '${VMPassword}' | sudo -S -s eval `"export HOME=``pwd``;bash ${remoteScript} > MountFloppy.log`""
    RunLinuxCmd -username $VMUserName -password $VMPassword -ip $Ipv4 -port $VMPort $MountFloppy -runAsSudo
    RemoteCopy -download -downloadFrom $Ipv4 -files "/home/${VMUserName}/state.txt" `
        -downloadTo $LogDir -port $VMPort -username $VMUserName -password $VMPassword
    RemoteCopy -download -downloadFrom $Ipv4 -files "/home/${VMUserName}/MountFloppy.log" `
        -downloadTo $LogDir -port $VMPort -username $VMUserName -password $VMPassword
    $contents = Get-Content -Path $stateFile
    if (($contents -eq "TestAborted") -or ($contents -eq "TestFailed")) {
        LogErr "Error: Running $remoteScript script failed on VM!"
        return "FAIL"
    }
    else {
        LogMsg "Test PASSED , Floppy Mounted on  VM!"
    }

}
Main -VMName $AllVMData.RoleName -HvServer $xmlConfig.config.Hyperv.Host.ServerName `
    -Ipv4 $AllVMData.PublicIP -VMPort $AllVMData.SSHPort `
    -VMUserName $user -VMPassword $password -RootDir $WorkingDirectory