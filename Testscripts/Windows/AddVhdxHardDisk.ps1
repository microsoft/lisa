# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Synopsis
    This setup script, that will run before the VM is booted, will create and add a VHDx to VM.

.Description
     This is a setup script that will run before the VM is booted.
     The script will create a .vhdx file, and mount it to the
     specified hard drive. If the hard drive does not exist, it
     will be created.

.Parameter vmName
    Name of the VM to remove disk from.

.Parameter hvServer
    Name of the Hyper-V server hosting the VM.

.Parameter testParams
    Test data for this test case

.Example
    .\Testscripts\Windows\AddVhdxHardDisk.ps1 -vmName myVM -hvServer localhost -testParams "SCSI=1,0,Dynamic,4096;ipv4=IPaddress"
#>
param([object] $AllVMData, [string] $TestParams)

$retVal = $true
$global:MinDiskSize = 1GB
$global:DefaultDynamicSize = 127GB
$SCSICount = 0
$IDECount = 0
$diskCount=$null
$lun=$null
$vmGeneration=$null
$clusterVm=$null

############################################################################
#
# Create-HardDrive
#
# Description
#     If the -SCSI options is false, an IDE drive is created
#
############################################################################
function Create-HardDrive( [string] $vmName, [string] $server, [System.Boolean] $SCSI, [int] $ControllerID,
                          [int] $Lun, [string] $vhdType, [string] $sectorSizes) {
    $retVal = $false
    Write-LogInfo "Create-HardDrive $vmName $server $scsi $controllerID $lun $vhdType"

    #
    # Make sure it's a valid IDE ControllerID. For IDE, it must 0 or 1.
    # For SCSI it must be 0, 1, 2, or 3
    #
    $controllerType = "IDE"
    if ($SCSI) {
        $controllerType = "SCSI"

        if ($ControllerID -lt 0 -or $ControllerID -gt 3) {
            Write-LogErr "Create-HardDrive was passed a bad SCSI Controller ID: $ControllerID"
            return $false
        }

        #
        # Create the SCSI controller if needed
        #
        $sts = Create-Controller -vmName $vmName -server $server -controllerID $controllerID
        if (-not $sts[$sts.Length-1]) {
            Write-LogErr "Unable to create SCSI controller $controllerID"
            return $false
        }
    } else {
        # Make sure the controller ID is valid for IDE
        if ($ControllerID -lt 0 -or $ControllerID -gt 1) {
            Write-LogErr "Create-HardDrive was passed an invalid IDE Controller ID: $ControllerID"
            return $False
        }
    }

    #
    # Return error if the hard drive already exists
    #
    $drive = Get-VMHardDiskDrive -VMName $vmName -ControllerNumber $controllerID -ControllerLocation $Lun `
                -ControllerType $controllerType -ComputerName $server
    if ($drive) {
        if ( $controllerID -eq 0 -and $Lun -eq 0 ) {
            Write-LogErr "Drive $controllerType $controllerID $Lun already exists"
            return $retVal
        } else {
            Remove-VMHardDiskDrive $drive
        }
    }

    $dvd = Get-VMDvdDrive -VMName $vmName -ComputerName $hvServer
    if ($dvd) {
        Remove-VMDvdDrive $dvd
    }

    #
    # Create the .vhd file if it does not already exist, then create the drive and mount the .vhdx
    # Checking if the VM might be running in a cluster
    #
    $clusterVm = Invoke-Command -ComputerName $server -ScriptBlock {
        (Get-WindowsOptionalFeature -Online -FeatureName "FailoverCluster-PowerShell").State -eq "Enabled"
    }
    if ($clusterVm -and (Get-ClusterSharedVolume -ErrorAction SilentlyContinue)) {
        $defaultVhdPath = (Get-ClusterSharedVolume).SharedVolumeInfo.FriendlyVolumeName
    } else {
        $hostInfo = Get-VMHost -ComputerName $server
        if (-not $hostInfo) {
            Write-LogErr "Unable to collect Hyper-V settings for ${server}"
            return $False
        }
        $defaultVhdPath = $hostInfo.VirtualHardDiskPath
    }

    if (-not $defaultVhdPath.EndsWith("\")) {
        $defaultVhdPath += "\"
    }

    $vhdName = $defaultVhdPath + $vmName + "-" + $controllerType + "-" + $controllerID + "-" + $lun + "-" + $vhdType + ".vhdx"
    if (Test-Path $vhdName) {
        Remove-Item $vhdName
    }

    $fileInfo = Get-RemoteFileInfo -filename $vhdName -server $server
    if (-not $fileInfo) {
      $nv = $null
      switch ($vhdType)
      {
          "Dynamic"
              {
                  $nv = New-Vhd -Path $vhdName -size $global:MinDiskSize -Dynamic -LogicalSectorSizeBytes ([int] $sectorSize) -ComputerName $server
              }
          "Fixed"
              {
                  $nv = New-Vhd -Path $vhdName -size $global:MinDiskSize -Fixed -LogicalSectorSizeBytes ([int] $sectorSize) -ComputerName $server
              }

          default
              {
                Write-LogErr "Unknown VHD type ${vhdType}"
                  return $False
              }
       }
        if ($nv -eq $null) {
            Write-LogErr "New-VHD failed to create the new .vhd file: $($vhdName)"
            return $False
        }
    }

    $error.Clear()
    Add-VMHardDiskDrive -VMName $vmName -Path $vhdName -ControllerNumber $controllerID `
     -ControllerLocation $Lun -ControllerType $controllerType -ComputerName $server
    if ($error.Count -gt 0) {
        Write-LogErr "Add-VMHardDiskDrive failed to add drive on ${controllerType} ${controllerID} ${Lun}s"
        $error[0].Exception
        return $retVal
    }

    "Success"
    $retVal = $True
    return $retVal
}

############################################################################
#
# Main entry point for script
#
############################################################################
function Main {
    param (
        $VmName,
        $hvServer,
        $rootDir,
        $testParams
    )

    # Check input arguments
    if ($vmName -eq $null -or $vmName.Length -eq 0) {
        Write-LogErr "VM name is null"
        return $False
    }

    if ($hvServer -eq $null -or $hvServer.Length -eq 0) {
        Write-LogErr "hvServer is null"
        return $False
    }

    if ($testParams -eq $null -or $testParams.Length -lt 3) {
        Write-LogErr "No testParams provided"
        return $False
    }

    $params = $testParams.TrimEnd(";").Split(";")
    foreach ($p in $params) {
        $fields = $p.Split("=")
        # Lisav2 framework supports the param with unique name.
        # Modifying the input SCSI_ and IDE_ multiple params and rebuilding testParams
        $var = $fields[0].Trim()
        if ($var -match "SCSI_") {
            $var = "SCSI"
        }
        elseif ($var -match "IDE_") {
            $var = "IDE"
        }
        switch ($var)
        {
        "rootDIR"   { $rootDir = $fields[1].Trim() }
        "diskCount"   { $diskCount = $fields[1].Trim() }
        "SCSI"  { $SCSICount = $SCSICount +1 }
        "IDE"  { $IDECount = $IDECount +1 }
        default     {}  # unknown param - just ignore it
        }
    }

    cd $rootDir

    $vmGeneration = Get-VMGeneration -vmName $vmName -hvServer $hvServer
    if ($IDECount -ge 1 -and $vmGeneration -eq 2) {
        Write-LogInfo "Generation 2 VM does not support IDE disk, please skip this case in the test script"
        return $True
    }
    # if define diskCount number, only support one SCSI parameter
    if ($diskCount -ne $null) {
        if ($SCSICount -gt 1 -or $IDECount -gt 0) {
            Write-LogErr "Invalid SCSI/IDE arguments, only support to define one SCSI disk"
            return $False
        }

        # We will limit SCSI disk number <= 64
        if ($diskCount -lt 0 -or $diskCount -gt 64) {
            Write-LogErr "Only support less than 64 SCSI disks"
            return $false
        }
    }

    foreach ($p in $params)
    {
        if ($p.Trim().Length -eq 0) {
            continue
        }

        # a parameter has the form of var_name = 'value'
        # here we parse and split the paramters to ensure that a parameter
        # does contain a value.
        $p -match '^([^=]+)=(.+)' | Out-Null
        if ($Matches[1,2].Length -ne 2) {
        Write-LogInfo "Warn : test parameter '$p' is being ignored because it appears to be malformed"
            continue
        }

        # Matches[1] represents the parameter name
        # Matches[2] is the value content of the parameter
        $controllerType = $Matches[1].Trim()
        $value = $Matches[2].Trim()
        if ($controllerType -match "SCSI_") {
            $controllerType = "SCSI"
        }
        elseif ($controllerType -match "IDE_") {
            $controllerType = "IDE"
        }


        if (@("IDE", "SCSI") -notcontains $controllerType) {
            # Not a test parameter we are concerned with
            continue
        }

        $SCSI = $false
        if ($controllerType -eq "SCSI") {
            $SCSI = $true
        }

        $diskArgs = $value.Split(',')
        if ($diskArgs.Length -lt 3 -or $diskArgs.Length -gt 5) {
            Write-LogErr "Incorrect number of arguments: $p"
            $retVal = $false
            continue
        }

        $controllerID = $diskArgs[0].Trim()
        if ($vmGeneration -eq 1) {
            $lun = [int]($diskArgs[1].Trim())
        } else {
            $lun = [int]($diskArgs[1].Trim()) +1
        }
        $vhdType = $diskArgs[2].Trim()

        $sectorSize = 512
        if ($diskArgs.Length -ge 4) {
            $sectorSize = $diskArgs[3].Trim()
            if ($sectorSize -ne "4096" -and $sectorSize -ne "512") {
                Write-LogErr "Bad sector size: ${sectorSize}"
                return $False
            }
        }

        # if 5th element is specified, it will be used, else it will be used the default size: MinDiskSize=1GB
        if ($diskArgs.Length -eq 5) {
            $global:MinDiskSize = Convert-StringToDecimal -str ($diskArgs[4].Trim())
            # To avoid PSUseDeclaredVarsMoreThanAssignments warning when run PS Analyzer
            Write-LogInfo "global parameter MinDiskSize is set to $global:MinDiskSize"
        }

        if (@("Fixed", "Dynamic") -notcontains $vhdType) {
            Write-LogErr "Unknown disk type: $p"
            $retVal = $false
            continue
        }

        # here only test scsi when use diskCount
        if ($diskCount -ne $null -and $SCSI -eq $true) {
            if ($vmGeneration -eq 1) {
                $startLun = 0
                $endLun = $diskCount-1
            } else {
                $startLun = 1
                $endLun = $diskCount-2
            }
        } else {
        $startLun = $lun
        $endLun = $lun
        }
        for ($lun=$startLun; $lun -le $endLun; $lun++) {
            "Create-HardDrive $vmName $hvServer $scsi $controllerID $Lun $vhdType $sectorSize"
            $sts = Create-HardDrive -vmName $vmName -server $hvServer -SCSI:$SCSI -ControllerID $controllerID `
            -Lun $Lun -vhdType $vhdType -sectorSize $sectorSize
            if (-not $sts[$sts.Length-1]) {
                Write-LogErr "Failed to create hard drive!"
                $sts
                $retVal = $false
                continue
            }
        }
    }
    return $retVal
}

Main -VmName $AllVMData.RoleName -hvServer $GlobalConfig.Global.Hyperv.Hosts.ChildNodes[0].ServerName `
        -testParams $TestParams -rootDir $WorkingDirectory
