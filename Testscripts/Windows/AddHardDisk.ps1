# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Synopsis
    Setup script that will add a Hard disk to a VM.

.Description
     This is a setup script that will run before the VM is booted.
     The script will create a .vhd file, and mount it to the
     specified hard drive.  If the hard drive does not exist, it
     will be created.
#>

param([string] $vmName, [string] $hvServer, [string] $TestParams)

$MinDiskSize = "1GB"

function New-SCSIController {
    param (
        [string] $VMName,
        [string] $Server,
        [string] $ControllerID
    )

    if ($ControllerID -lt 0 -or $ControllerID -gt 3) {
        LogErr "Bad SCSI controller ID: $controllerID"
        return $False
    }

    # Check if the controller already exists
    # Note: If you specify a specific ControllerID, Get-VMDiskController always returns
    #       the last SCSI controller if there is one or more SCSI controllers on the VM.
    #       To determine if the controller needs to be created, count the number of
    #       SCSI controllers.

    $maxControllerID = 0
    $CreateSCSIController = $true
    $controllers = Get-VMScsiController -VMName $VMName -ComputerName $Server

    if ($null -ne $controllers) {
        if ($controllers -is [array]) {
            $maxControllerID = $controllers.Length
        } else {
            $maxControllerID = 1
        }
        if ($ControllerID -lt $maxControllerID) {
            LogMsg "Controller exists - controller not created"
            $CreateSCSIController = $false
        }
    }

    # If needed, create the controller
    if ($CreateSCSIController) {
        Add-VMSCSIController -VMName $VMName -ComputerName $Server -Confirm:$false
        if($? -ne $true) {
            LogErr "Add-VMSCSIController failed to add 'SCSI Controller $ControllerID'"
            return $False
        } else {
            LogMsg "SCSI Controller successfully added"
            return $True
        }
    }
}

function New-PassThruDrive {
    param (
        [string] $vmName,
        [string] $server,
        [switch] $scsi,
        [string] $controllerID,
        [string] $Lun,
        [int] $vmGen
    )

    $controllertype = "IDE"
    if ($scsi) {
        $controllertype = "SCSI"

        if ($ControllerID -lt 0 -or $ControllerID -gt 3) {
            LogErr "New-HardDrive was passed a bad SCSI Controller ID: $ControllerID"
            return $False
        }

        # Create the SCSI controller if needed
        $sts = New-SCSIController $vmName $server $controllerID

        if (-not $sts[$sts.Length-1]) {
            LogErr "Unable to create SCSI controller $controllerID"
            return $False
        }

        $drive = Get-VMScsiController -VMName $vmName -ControllerNumber $ControllerID -ComputerName $server | `
            Get-VMHardDiskDrive -ControllerLocation $Lun
    } else {
        $drive = Get-VMIdeController -VMName $vmName -ComputerName $server -ControllerNumber $ControllerID | `
            Get-VMHardDiskDrive -ControllerLocation $Lun
    }

    if ($drive) {
        if ($controllerID -eq 0 -and $Lun -eq 0 ) {
            LogErr "drive $controllerType $controllerID $Lun already exists"
            return $False
        } else {
            Remove-VMHardDiskDrive $drive
        }
    }

    if (($vmGen -eq 1) -and ($controllerType -eq "IDE")) {
        $dvd = Get-VMDvdDrive -VMName $vmName -ComputerName $server
        if ($dvd) {
            Remove-VMDvdDrive $dvd
        }
    }

    # Create the .vhd file if it does not already exist, then create the drive and mount the .vhdx
    $hostInfo = Get-VMHost -ComputerName $server
    if (-not $hostInfo) {
        LogErr "Unable to collect Hyper-V settings for ${server}"
        return $False
    }

    $defaultVhdPath = $hostInfo.VirtualHardDiskPath
    if (-not $defaultVhdPath.EndsWith("\")) {
        $defaultVhdPath += "\"
    }

    $vhdName = ("{0}{1}-{2}-{3}-{4}-pass.vhd" `
        -f @($defaultVhdPath, $vmName, $controllerType, $controllerID, $Lun))
    if(Test-Path $vhdName) {
        Dismount-VHD -Path $vhdName -ErrorAction Ignore
        Remove-Item $vhdName
    }
    $newVhd = $null

    $newVhd = New-VHD -Path $vhdName -size 1GB -ComputerName $server -Fixed
    if ($null -eq $newVhd) {
        LogErr "New-VHD failed to create the new .vhd file: $($vhdName)"
        return $False
    }

    $newVhd = $newVhd | Mount-VHD -Passthru
    $physDisk = $newVhd | Initialize-Disk -PartitionStyle MBR -PassThru
    $physDisk | Set-Disk -IsOffline $true

    $ERROR.Clear()
    $physDisk | Add-VMHardDiskDrive -VMName $vmName -ControllerNumber $controllerID `
                    -ControllerLocation $Lun -ControllerType $controllerType -ComputerName $server
    if ($ERROR.Count -gt 0) {
            LogErr "Add-VMHardDiskDrive failed to add drive on ${controllerType} ${controllerID} ${Lun}s"
            return $False
    }

    LogMsg "Successfully attached passthrough drive"
    return $True
}

function New-HardDrive
{
    param (
        [string] $vmName,
        [string] $server,
        [System.Boolean] $SCSI,
        [int] $ControllerID,
        [int] $Lun,
        [string] $vhdType,
        [String] $newSize,
        [int] $vmGen
    )

    LogMsg "Enter New-HardDrive $vmName $server $scsi $controllerID $lun $vhdType"

    $controllerType = "IDE"

    # Make sure it's a valid IDE ControllerID.  For IDE, it must 0 or 1.
    # For SCSI it must be 0, 1, 2, or 3

    if ($SCSI) {
        if ($ControllerID -lt 0 -or $ControllerID -gt 3) {
            LogMsg "New-HardDrive was passed a bad SCSI Controller ID: $ControllerID"
            return $False
        }

        # Create the SCSI controller if needed
        $sts = New-SCSIController $vmName $server $controllerID
        if (-not $sts) {
            LogErr "Unable to create SCSI controller $controllerID"
            return $False
        }

        $controllerType = "SCSI"
    } else {
        if ($ControllerID -lt 0 -or $ControllerID -gt 1) {
            LogErr "New-HardDrive was passed an invalid IDE Controller ID: $ControllerID"
            return $False
        }
    }

    # If the hard drive exists, complain. Otherwise, add it
    $drive = Get-VMHardDiskDrive -VMName $vmName -ComputerName $hvServer `
        -ControllerType $controllerType -ControllerNumber $controllerID -ControllerLocation $Lun
    if ($drive) {
        if ( $controllerID -eq 0 -and $Lun -eq 0 ) {
            LogErr "drive $controllerType $controllerID $Lun already exists"
            return $False
        } else {
            Remove-VMHardDiskDrive $drive
        }
    }

    if (($vmGen -eq 1) -and ($controllerType -eq "IDE")) {
        $dvd = Get-VMDvdDrive -VMName $vmName -ComputerName $hvServer
        if ($dvd) {
            Remove-VMDvdDrive $dvd
        }
    }

    # Create the .vhd file if it does not already exist
    $obj = Get-WmiObject -ComputerName $hvServer -Namespace "root\virtualization\v2" `
        -Class "MsVM_VirtualSystemManagementServiceSettingData"

    $defaultVhdPath = $obj.DefaultVirtualHardDiskPath
    if (-not $defaultVhdPath.EndsWith("\")) {
        $defaultVhdPath += "\"
    }

    $newVHDSize = Convert-StringToUInt64 $newSize
    $vhdName = ("{0}{1}-{2}-{3}-{4}-{5}.vhd" `
        -f @($defaultVhdPath, $vmName, $controllerType, $controllerID, $Lun, $vhdType))

    if(Test-Path $vhdName) {
        Dismount-VHD -Path $vhdName -ErrorAction Ignore
        Remove-Item $vhdName
    }
    $fileInfo = Get-RemoteFileInfo -filename $vhdName -server $hvServer

    if (-not $fileInfo) {
        $newVhd = $null
        switch ($vhdType) {
            "Dynamic" {
                $newvhd = New-VHD -Path $vhdName  -size $newVHDSize -ComputerName $server `
                    -Dynamic -ErrorAction SilentlyContinue
            }
            "Fixed" {
                $newVhd = New-VHD -Path $vhdName -size $newVHDSize -ComputerName $server `
                    -Fixed -ErrorAction SilentlyContinue
            }
            "Physical" {
                LogMsg "Searching for physical drive..."
                $newVhd = (Get-Disk | Where-Object {
                    ($_.OperationalStatus -eq "Offline") -and ($_.Number -eq "$PhyNumber")
                }).Number
                LogMsg "Physical drive found: $newVhd"
            }
            "RAID" {
                LogMsg "Searching for RAID disks..."
                $newVhd = (Get-Disk | Where-Object {
                    ($_.OperationalStatus -eq "Offline" -and $_.Number -gt "$PhyNumber")
                }).Number
                LogMsg "Physical drive found: $newVhd"
                Start-Sleep 5
            }
            "Diff" {
                $parentVhdName = $defaultVhdPath + "icaDiffParent.vhd"
                $parentInfo = Get-RemoteFileInfo -filename $parentVhdName -server $hvServer
                if (-not $parentInfo) {
                    LogErr "parent VHD does not exist: ${parentVhdName}"
                    return $False
                }
                $newVhd = New-VHD -Path $vhdName -ParentPath $parentVhdName -ComputerName $server -Differencing
            }
            default {
                LogErr "unknow vhd type of ${vhdType}"
                return $False
            }
        }
        if ($null -eq $newVhd) {
            #On WS2012R2, New-VHD cmdlet throws error even after successfully creation of VHD
            #so re-checking if the VHD available on the server or not
            $newVhdInfo = Get-RemoteFileInfo -filename $vhdName -server $hvServer
            if ($null -eq $newVhdInfo) {
                LogErr "New-VHD failed to create the new .vhd file: $($vhdName)"
                return $False
            }
        }
    }

    # Attach the .vhd file to the new drive
    if ($vhdType -eq "RAID") {
        LogMsg "Attaching physical drive for RAID..."
        $ERROR.Clear()
        foreach ($i in $newvhd) {
            $disk = Add-VMHardDiskDrive -VMName $vmName -ComputerName $server `
                -ControllerType $controllerType -ControllerNumber $controllerID -DiskNumber $i
            if ($ERROR.Count -gt 0) {
                LogErr "Unable to attach physical drive: $i."
                return $False
            }
        }
    } elseif ($vhdType -eq "Physical") {
        LogMsg "Attaching physical drive..."
        $ERROR.Clear()
        $disk = Add-VMHardDiskDrive -VMName $vmName -ComputerName $server `
            -ControllerType $controllerType -ControllerNumber $controllerID -DiskNumber $newVhd
        if ($ERROR.Count -gt 0) {
            LogErr "Unable to attach physical drive."
            return $False
        }
    } else {
        $disk = Add-VMHardDiskDrive -VMName $vmName -ComputerName $server `
            -ControllerType $controllerType -ControllerNumber $controllerID `
            -ControllerLocation $Lun -Path $vhdName
    }

    if ($disk -contains "Exception") {
        LogErr "Add-VMHardDiskDrive failed to add $($vhdName) to $controllerType $controllerID $Lun $vhdType"
        return $False
    }

    LogMsg "Success"
    return $retVal
}


function Main {
    param (
        $VMName,
        $HvServer,
        $TestParams
    )

    if ($null -eq $testParams) {
        LogErr "No testParams provided"
        LogErr "AddHardDisk.ps1 requires test params"
        return $False
    }

    $vmGen = Get-VMGeneration $VMName $HvServer
    if ($vmGen -ne 1) {
        throw "VHD is not supported by Gen 2 VMs"
    }

    # Parse the testParams string
    $params = $testParams.Split(';')
    foreach ($p in $params) {
        if ($p.Trim().Length -eq 0) {
            continue
        }

        $temp = $p.Trim().Split('=')
        if ($temp.Length -ne 2) {
            LogErr "test parameter '$p' is being ignored because it appears to be malformed"
            continue
        }
        $controllerType = $temp[0]
        if (@("IDE", "SCSI") -notcontains $controllerType) {
            continue
        }
        $SCSI = $false
        if ($controllerType -eq "SCSI") {
            $SCSI = $true
        }

        $diskArgs = $temp[1].Trim().Split(',')
        if ($diskArgs.Length -ne 4 -and $diskArgs.Length -ne 3) {
            LogErr "Incorrect number of arguments: $p"
            return $False
        }

        $controllerID = $diskArgs[0].Trim()
        $lun = $diskArgs[1].Trim()
        $vhdType = $diskArgs[2].Trim()

        $VHDSize = $MinDiskSize
        if ($diskArgs.Length -eq 4) {
            $VHDSize = $diskArgs[3].Trim()
        }

        if (@("Fixed", "Dynamic", "PassThrough", "Diff", "Physical", "RAID") -notcontains $vhdType) {
            LogErr "Unknown disk type: $p"
            return $False
        }

        if ($vhdType -eq "PassThrough") {
            LogMsg "New-PassThruDrive $vmName $hvServer $scsi $controllerID $Lun"
            $sts = New-PassThruDrive $vmName $hvServer -SCSI:$scsi $controllerID $Lun $vmGen
            $results = [array]$sts
            if (-not $results[$results.Length-1]) {
                LogErr "Failed to create PassThrough drive"
                return $False
            }
        } else {
            LogMsg "New-HardDrive $vmName $hvServer $scsi $controllerID $Lun $vhdType"
            $sts = New-HardDrive -vmName $vmName -server $hvServer -SCSI:$SCSI `
                -ControllerID $controllerID -Lun $Lun -vhdType $vhdType -newSize $VHDSize
        }
    }

    return $True
}

Main -VMName $AllVMData.RoleName -hvServer $xmlConfig.config.Hyperv.Hosts.ChildNodes[0].ServerName `
         -TestParams $TestParams -vmGen $vmGen
