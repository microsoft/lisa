# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Synopsis
    This setup script, which runs before the VM is booted, will add an additional differencing hard drive to the specified VM.

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

param([string] $TestParams)

$controllerType = $null
$controllerID = $null
$lun = $null
$vhdType = $null
$parentVhd = $null
$vhdFormat =$null
$vmGeneration = $null

function New-ParentVhd {
    param (
        [string] $vhdFormat,
        [string] $server
    )

    $hostInfo = Get-VMHost -ComputerName $server
    if (-not $hostInfo) {
            LogErr "Unable to collect Hyper-V settings for ${server}"
            return $False
    }
    $defaultVhdPath = $hostInfo.VirtualHardDiskPath
    if (-not $defaultVhdPath.EndsWith("\")) {
            $defaultVhdPath += "\"
    }

    $parentVhdName = $defaultVhdPath + $vmName + "_Parent." + $vhdFormat
    if(Test-Path $parentVhdName) {
        Remove-Item $parentVhdName
    }

    $fileInfo = Get-RemoteFileInfo -filename $parentVhdName -server $server
    if (-not $fileInfo) {
        $nv = New-Vhd -Path $parentVhdName -SizeBytes 2GB -Dynamic -ComputerName $server
        if ($null -eq $nv) {
            LogErr "New-VHD failed to create the new .vhd file: $parentVhdName"
            return $False
        }
    }
    return $parentVhdName
}

function Main {
    param (
        $VMName,
        $HvServer,
        $TestParams
    )

    # Parse the testParams string
    $params = $testParams.Split(';')
    foreach ($p in $params) {
        if ($p.Trim().Length -eq 0) {
            continue
        }

        $tokens = $p.Trim().Split('=')

        if ($tokens.Length -ne 2) {
            # Just ignore it
            continue
        }

        $lValue = $tokens[0].Trim()
        $rValue = $tokens[1].Trim()

        # ParentVHD test param
        if ($lValue -eq "ParentVHD") {
            $parentVhd = $rValue
            continue
        }

        # vhdFormat test param
        if ($lValue -eq "vhdFormat") {
            $vhdFormat = $rValue
            continue
        }

        # Controller type testParam
        if (@("IDE", "SCSI") -contains $lValue) {
            $controllerType = $lValue
            $SCSI = $false

            if ($controllerType -eq "SCSI") {
                $SCSI = $true
            }

            $diskArgs = $rValue.Split(',')

            if ($diskArgs.Length -ne 3) {
                LogErr "Incorrect number of disk arguments: $p"
                return $False
            }

            $controllerID = $diskArgs[0].Trim()
            $lun = $diskArgs[1].Trim()
            $vhdType = $diskArgs[2].Trim()

            # Just a reminder. The test case is testing differencing disks.
            # If we are asked to create a disk other than a differencing disk,
            # then the wrong setup script was specified.
            if ($vhdType -ne "Diff") {
                LogErr "The differencing disk test requires a differencing disk"
                return $False
            }
        }
    }

    if (-not $rootDir) {
        LogErr "no rootdir was specified"
    } else {
        Set-Location $rootDir
    }

    # Make sure we have all the required data
    if (-not $controllerType) {
        LogErr "No controller type specified in the test parameters"
        return $False
    }

    $vmGeneration = Get-VMGeneration $vmName $hvServer
    if ( $controllerType -eq "IDE" -and $vmGeneration -eq 2 ) {
        LogMsg "Generation 2 VM does not support IDE disk, please skip this case in the test script"
        return $True
    }

    if (-not $controllerID) {
        LogErr "No controller ID specified in the test parameters"
        return $False
    }

    if (-not $lun) {
        LogErr "No LUN specified in the test parameters"
        return $False
    }

    if (-not $vhdFormat) {
        LogErr "No vhdFormat specified in the test parameters"
        return $False
    }

    if (-not $parentVhd) {
        # Create a new ParentVHD
        $parentVhd = New-ParentVhd $vhdFormat $hvServer
        if ($parentVhd -eq $False) {
            LogErr "Failed to create parent $vhdFormat on $hvServer"
            return $False
        } else {
            LogMsg "Parent disk $parentVhd created"
        }
    }

    # Make sure the disk does not already exist
    if ($SCSI) {
        if ($ControllerID -lt 0 -or $ControllerID -gt 3) {
            LogErr "CreateHardDrive was passed a bad SCSI Controller ID: $ControllerID"
            return $false
        }
        # Create the SCSI controller if needed
        $sts = Create-Controller $vmName $hvServer $controllerID
        if (-not $sts[$sts.Length-1]) {
            LogErr "Unable to create SCSI controller $controllerID"
            return $false
        }
    } else {
        if ($ControllerID -lt 0 -or $ControllerID -gt 1) {
            LogErr "CreateHardDrive was passed an invalid IDE Controller ID: $ControllerID"
            return $False
        }
    }


    if ($vmGeneration -eq 1) {
        $lun = [int]($diskArgs[1].Trim())
    } else {
        $lun = [int]($diskArgs[1].Trim()) +1
    }

    $dvd = Get-VMDvdDrive -VMName $vmName -ComputerName $hvServer
    if ($dvd) {
        Remove-VMDvdDrive $dvd
    }

    $drives = Get-VMHardDiskDrive -VMName $vmName -ComputerName $hvServer -ControllerType $controllerType `
        -ControllerNumber $controllerID -ControllerLocation $lun
    if ($drives) {
        LogErr "drive $controllerType $controllerID $Lun already exists"
        return $False
    }

    $hostInfo = Get-VMHost -ComputerName $hvServer
    if (-not $hostInfo) {
        LogErr "Unable to collect Hyper-V settings for ${hvServer}"
        return $False
    }

    $defaultVhdPath = $hostInfo.VirtualHardDiskPath
    if (-not $defaultVhdPath.EndsWith("\")) {
        $defaultVhdPath += "\"
    }

    if ($parentVhd.EndsWith(".vhd")) {
        $vhdFormat = "vhd"
    } else {
        $vhdFormat = "vhdx"
    }
    $vhdName = ("{0}{1}-{2}-{3}-{4}-Diff.{5}" `
        -f @($defaultVhdPath, $vmName, $controllerType, $controllerID, $lun, $vhdFormat))


    $vhdFileInfo = Get-RemoteFileInfo $vhdName $hvServer
    if ($vhdFileInfo) {
        $delSts = $vhdFileInfo.Delete()
        if (-not $delSts -or $delSts.ReturnValue -ne 0) {
            LofErr "unable to delete the existing .vhd file: ${vhdFilename}"
            return $False
        }
    }

    # Make sure the parent VHD is an absolute path, and it exists
    $parentVhdFilename = $parentVhd
    if (-not [System.IO.Path]::IsPathRooted($parentVhd)) {
        $parentVhdFilename = $defaultVhdPath + $parentVhd
    }

    $parentFileInfo = Get-RemoteFileInfo $parentVhdFilename $hvServer
    if (-not $parentFileInfo) {
        LogErr "Cannot find parent VHD file: ${parentVhdFilename}"
        return $False
    }

    # Create the .vhd file
    $newVhd = New-Vhd -Path $vhdName -ParentPath $parentVhdFilename -ComputerName $hvServer -Differencing
    if (-not $newVhd) {
        LogErr "unable to create a new .vhd file"
        return $False
    }

    # Just double check to make sure the .vhd file is a differencing disk
    if ($newVhd.ParentPath -ne $parentVhdFilename) {
        LogErr "the VHDs parent does not match the provided parent vhd path"
        return $False
    }

    # Attach the .vhd file to the new drive
    $error.Clear()
    Add-VMHardDiskDrive -VMName $vmName -ComputerName $hvServer -ControllerType $controllerType `
        -ControllerNumber $controllerID -ControllerLocation $lun -Path $vhdName
    if ($error.Count -gt 0) {
        LogErr "Add-VMHardDiskDrive failed to add drive on ${controllerType} ${controllerID} ${Lun}s"
        return $False
    } else {
        LogMsg "Child disk $vhdName created and attached to ${controllerType} : ${controllerID} : ${Lun}"
        return $True
    }
}

Main -VMName $AllVMData.RoleName -hvServer $xmlConfig.config.Hyperv.Hosts.ChildNodes[0].ServerName `
         -TestParams $TestParams
