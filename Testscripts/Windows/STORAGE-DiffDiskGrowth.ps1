# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Synopsis
    This test script, which runs inside VM it mount the drive and perform write operations on diff disk.
    It then checks to ensure that parent disk size does not change.

.Description
    ControllerType=Controller Index, Lun or Port, vhd type

   Where
      ControllerType   = The type of disk controller.  IDE or SCSI
      Controller Index = The index of the controller, 0 based.
                         Note: IDE can be 0 - 1, SCSI can be 0 - 3
      Lun or Port      = The IDE port number of SCSI Lun number
      Vhd Type         = Type of VHD to use.
                         Valid VHD types are:
                             Dynamic
                             Fixed
                             Diff (Differencing)

   The following are some examples:
   SCSI=0,0,Diff : Add a hard drive on SCSI controller 0, Lun 0, vhd type of Dynamic
   IDE=1,1,Diff  : Add a hard drive on IDE controller 1, IDE port 1, vhd type of Diff

   Note: This setup script only adds differencing disks.
#>

param ([String] $TestParams)

function Main {
    param (
        $VMname,
        $HvServer,
        $Ipv4,
        $VMPort,
        $VMUserName,
        $VMPassword,
        $RootDir,
        $TestParams
    )

    $controllerType = $null
    $controllerID = $null
    $lun = $null
    $vhdType = $null
    $vhdName = $null
    $vhdFormat = $null
    $vmGeneration = $null

    $REMOTE_SCRIPT = "STORAGE-PartitionDisks.sh"
    $rootUser = "root"

    $params = $testParams.Split(';')
    foreach ($p in $params) {
        if ($p.Trim().Length -eq 0) {
            continue
        }
        $tokens = $p.Trim().Split('=')
        if ($tokens.Length -ne 2) {
            Continue
        }

        $lValue = $tokens[0].Trim()
        $rValue = $tokens[1].Trim()

        if ($lValue -eq "ParentVHD") {
            continue
        }
        if ($lValue -eq "vhdFormat") {
            $vhdFormat = $rValue
            continue
        }
        if (@("IDE", "SCSI") -contains $lValue) {
            $controllerType = $lValue
            $diskArgs = $rValue.Trim().Split(',')

            if ($diskArgs.Length -ne 3) {
                LogErr "Incorrect number of arguments: $p"
                Continue
            }

            $controllerID = $diskArgs[0].Trim()
            $lun = $diskArgs[1].Trim()
            $vhdType = $diskArgs[2].Trim()
            Continue
        }
        if ($lValue -eq "FILESYS") {
            $FILESYS = $rValue
            Continue
        }
    }

    if ($null -eq $rootdir) {
        LogErr "Test parameter rootdir was not specified"
        return "FAIL"
    } else {
        Set-Location $rootdir
    }

    if (-not $controllerType) {
        LogErr "Missing controller type in test parameters"
        return "FAIL"
    }

    $vmGeneration = Get-VMGeneration $vmName $hvServer
    if ( $controllerType -eq "IDE" -and $vmGeneration -eq 2 ) {
        LogErr "Generation 2 VM does not support IDE disk, skip test"
        return "FAIL"
    }
    if (-not $controllerID) {
        LogErr "Missing controller index in test parameters"
        return "FAIL"
    }
    if (-not $lun) {
        LogErr "Missing lun in test parameters"
        return "FAIL"
    }
    if (-not $vhdType) {
        LogErr "Missing vhdType in test parameters"
        return "FAIL"
    }
    if (-not $vhdFormat) {
        LogErr "No vhdFormat specified in the test parameters"
        return "FAIL"
    }
    if (-not $FILESYS) {
        LogErr "Test parameter FILESYS was not specified"
        return "FAIL"
    }

    $hostInfo = Get-VMHost -ComputerName $hvServer
    if (-not $hostInfo) {
        LogErr "Unable to collect Hyper-V settings for ${hvServer}"
        return "FAIL"
    }

    $defaultVhdPath = $hostInfo.VirtualHardDiskPath
    if (-not $defaultVhdPath.EndsWith("\")) {
        $defaultVhdPath += "\"
    }

    if ($vmGeneration -eq 1) {
        $lun = [int]($diskArgs[1].Trim())
    } else {
        $lun = [int]($diskArgs[1].Trim()) +1
    }

    $vhdName = ("{0}{1}-{2}-{3}-{4}-Diff.{5}" `
        -f @($defaultVhdPath, $vmName, $controllerType, $controllerID, $lun, $vhdFormat))

    # The .vhd file should have been created by our
    # setup script. Make sure the .vhd file exists.
    $vhdFileInfo = GetRemoteFileInfo $vhdName $hvServer
    if (-not $vhdFileInfo) {
        LogErr "VHD file does not exist: ${vhdFilename}"
        return "FAIL"
    }

    $vhdInitialSize = $vhdFileInfo.FileSize

    # Make sure the .vhd file is a differencing disk
    $vhdInfo = Get-VHD -path $vhdName -ComputerName $hvServer
    if (-not $vhdInfo) {
        LogErr "Unable to retrieve VHD information on VHD file: ${vhdFilename}"
        return "FAIL"
    }
    if ($vhdInfo.VhdType -ne "Differencing") {
        LogErr "VHD `"${vhdName}`" is not a Differencing disk"
        return "FAIL"
    }

    # Collect info on the parent VHD
    $parentVhdFilename = $vhdInfo.ParentPath

    $parentFileInfo = Get-RemoteFileInfo $parentVhdFilename $hvServer
    if (-not $parentFileInfo) {
        LogErr"Unable to collect file information on parent VHD `"${parentVhd}`""
        return "FAIL"
    }

    $parentInitialSize = $parentFileInfo.FileSize
    Start-Sleep -Seconds 30

    # Format the disk
    $scriptPath = Join-Path ".\Testscripts\Linux" $REMOTE_SCRIPT
    RemoteCopy -uploadTo $Ipv4 -port $VMPort -password $VMPassword -username $rootUser `
        -files $scriptPath -upload
    $retVal = RunLinuxCmd -username $rootUser -password $VMPassword -ip $Ipv4 -port $VMPort `
        -command "bash ~/${REMOTE_SCRIPT}"
    if (-not $retVal) {
        LogErr "ERROR executing $REMOTE_SCRIPT on VM. Exiting test case!"
        return "FAIL"
    }

    # Tell the guest OS on the VM to mount the differencing disk
    $retVal = RunLinuxCmd -username $rootUser -password $VMPassword -ip $Ipv4 -port $VMPort `
        -command "mkdir -p /mnt/2/DiffDiskGrowthTestCase"
    if (-not $retVal) {
        LogErr "Unable to send mkdir request to VM"
        return "FAIL"
    }

    # Tell the guest OS to write a few MB to the differencing disk
    $retVal = RunLinuxCmd -username $rootUser -password $VMPassword -ip $Ipv4 -port $VMPort `
        -command "dd if=/dev/sdb1 of=/mnt/2/DiffDiskGrowthTestCase/test.dat count=2048 > /dev/null 2>&1"
    if (-not $retVal) {
        LogErr "Unable to send command to VM to grow the .vhd"
        return "FAIL"
    }

    # Tell the guest OS on the VM to unmount the differencing disk
    $retVal = RunLinuxCmd -username $rootUser -password $VMPassword -ip $Ipv4 -port $VMPort `
        -command "umount /mnt/1 | umount /mnt/2"
    if (-not $retVal) {
        LogErr "Unable to send umount request to VM"
        return "FAIL"
    }

    # Save the current size of the parent VHD and differencing disk
    $parentInfo = Get-RemoteFileInfo $parentVhdFilename $hvServer
    $parentFinalSize = $parentInfo.fileSize

    $vhdInfo = Get-RemoteFileInfo $vhdFilename $hvServer
    $vhdFinalSize = $vhdInfo.FileSize

    # Make sure the parent matches its initial size
    if ($parentFinalSize -eq $parentInitialSize) {
        LogMsg "The parent .vhd file did not change in size"
    }

    if ($vhdFinalSize -gt $vhdInitialSize)
    {
        LogMsg "The differencing disk grew in size from ${vhdInitialSize} to ${vhdFinalSize}"
    }

    LogMsg "Test finished with result: PASS"

    return "PASS"
}

Main -VMname $AllVMData.RoleName -HvServer $xmlConfig.config.Hyperv.Hosts.ChildNodes[0].ServerName `
    -Ipv4 $AllVMData.PublicIP -VMPort $AllVMData.SSHPort `
    -VMUserName $user -VMPassword $password -RootDir $WorkingDirectory `
    -TestParams $TestParams
