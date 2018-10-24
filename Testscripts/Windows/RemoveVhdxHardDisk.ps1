# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Synopsis
    This cleanup script, which runs after the VM is shutdown, will remove VHDx disk(s) from VM.

.Description
   This is a cleanup script that will run after the VM shuts down.
   This script will delete the hard drive, and if no other drives
   are attached to the controller, delete the controller.

   Note: The controller will not be removed if it is an IDE.
         IDE Lun 0 will not be removed.
#>

param([string] $TestParams)

$SCSICount = 0
$IDECount = 0
$diskCount =$null
$vmGeneration = $null

function DeleteHardDrive {
    param (
        [string] $vmName, 
        [string] $hvServer, 
        [string] $controllerType, 
        [string] $arguments, 
        [int] $diskCount,
        [int] $vmGeneration
    )

    $scsi = $false
    $ide = $true
    
    if ($controllerType -eq "scsi") {
        $scsi = $true
        $ide = $false
    }

    # Extract the parameters in the arguments variable
    $controllerID = -1
    $lun = -1
    $fields = $arguments.Trim().Split(',')
    if (($fields.Length -lt 4) -or ($fields.Length -gt 5)) {
        LogErr "Incorrect number of arguments: $arguments"
        return $false
    }

    # Set and validate the controller ID and disk LUN
    $controllerID = $fields[0].Trim()
    if ($vmGeneration -eq 1) {
        $lun = [int]($fields[1].Trim())
    } else {
        $lun = [int]($fields[1].Trim()) +1
    }
    if ($scsi) {
        # Hyper-V only allows 4 SCSI controllers
        if ($controllerID -lt 0 -or $controllerID -gt 3) {
            LogErr "bad SCSI controllerID: $controllerID"
            return $false
        }
        # We will limit SCSI LUNs to 4 (1-64)
        if ($lun -lt 0 -or $lun -gt 64) {
            LogErr "bad SCSI Lun: $Lun"
            return $false
        }
    } elseif ($ide) {
        # Hyper-V creates 2 IDE controllers and we cannot add any more
        if ($controllerID -lt 0 -or $controllerID -gt 1) {
            LogErr "bad IDE controller ID: $controllerID"
            return $false
        }
        if ($lun -lt 0 -or $lun -gt 1) {
            LogErr "bad IDE Lun: $Lun"
            return $false
        }

        # Make sure we are not deleting IDE 0 0
        if ($Lun -eq 0 -and $controllerID -eq 0) {
            LogErr "Cannot delete IDE 0,0"
            return $false
        }
    } else {
        LogErr "Undefined controller type!"
        return $false
    }

    # Delete the drive if it exists
    $controller = $null
    $drive = $null

    if($ide) {
        $controller = Get-VMIdeController -VMName $vmName -ComputerName $hvServer `
            -ControllerNumber $controllerID
    }
    if($scsi) {
        $controller = Get-VMScsiController -VMName $vmName -ComputerName $hvServer `
            -ControllerNumber $controllerID
    }

    if ($controller) {
         # here only test scsi for adding multiple scsi
        if ($diskCount -gt 0 -and $scsi -eq $true) {
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
            $drive = Get-VMHardDiskDrive -VMName $vmName -ComputerName $hvServer `
                -ControllerType $controllerType -ControllerNumber $controllerID -ControllerLocation $lun
            if ($drive) {    
                LogMsg $drive.Path
                LogMsg "Removing $controllerType $controllerID $lun"
                $vhdxPath = $drive.Path
                $vhdxPathFormated = ("\\$hvServer\$vhdxPath").Replace(':','$')
                Remove-VMHardDiskDrive $drive
                LogMsg "Removing file $drive.path"
                Remove-Item $vhdxPathFormated
            } else {
                LogMsg "Drive $controllerType $controllerID,$Lun does not exist"
            }
        }
    } else {
        LogMsg "The controller $controllerType $controllerID does not exist"
    }

    return $retVal
}

function Main {
    param (
        $VMName,
        $HvServer,
        $TestParams
    )

    if ($null -eq $testParams -or $testParams.Length -lt 13) {
        # The minimum length testParams string is "IDE=1,1,Fixed
        LogErr "Error: No testParams provided"
        LogErr "The script $MyInvocation.InvocationName requires test parameters"
        return $false
    }

    $params = $testParams.Split(';')
    $params = $testParams.TrimEnd(";").Split(";")

    foreach ($p in $params) {
        $fields = $p.Split("=")

        switch ($fields[0].Trim()) {
            "diskCount"   { $diskCount = $fields[1].Trim() }
            "SCSI"  { $SCSICount = $SCSICount +1 }
            "IDE"  { $IDECount = $IDECount +1 }
            default     {}  # unknown param - just ignore it
        }
    }

    $vmGeneration = Get-VMGeneration $vmName $hvServer
    if ($IDECount -ge 1 -and $vmGeneration -eq 2 ) {
         LogErr "Generation 2 VM does not support IDE disk, please skip this case in the test script"
         return $false
    }

    # if define diskCount number, only support one SCSI parameter
    if ($null -ne $diskCount) {
        if ($SCSICount -gt 1 -or $IDECount -gt 0) {
            LogErr "Invalid SCSI/IDE arguments, only support to define one SCSI disk"
            return $false
        }
    }

    foreach ($p in $params) {
        if ($p.Trim().Length -eq 0) {
            continue
        }

        $p -match '^([^=]+)=(.+)' | Out-Null
        if ($Matches[1,2].Length -ne 2) {
            LogErr "bad test parameter: $p"
            return $false
            continue
        }

        # Matches[1] represents the parameter name
        # Matches[2] is the value content of the parameter
        $controllerType = $Matches[1].Trim().ToLower()
        if ($controllertype -ne "scsi" -and $controllerType -ne "ide") {
            # Just ignore the parameter
            continue
        }

        LogMsg "DeleteHardDrive $vmName $hvServer $controllerType $($Matches[2])"
        DeleteHardDrive -vmName $vmName -hvServer $hvServer -controllerType $controllertype `
            -arguments $Matches[2] -diskCount $diskCount -vmGeneration $vmGeneration
    }
    
    LogMsg "Vhdx Hard Drive Removed"
    return "PASS"
}

Main -VMName $AllVMData.RoleName -hvServer $xmlConfig.config.Hyperv.Hosts.ChildNodes[0].ServerName `
         -TestParams $TestParams
