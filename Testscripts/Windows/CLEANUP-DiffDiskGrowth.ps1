# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Synopsis
    This cleanup script, which runs after the VM is booted, removes a differencing disk from the specified VM.

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

param([String] $TestParams)

$controllerType = $null
$controllerID = $null
$lun = $null
$vhdType = $null
$parentVhd = $null
$controller = $null
$drive = $null
$vmGeneration = $null

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
            $IDE = $false
            
            if ($controllerType -eq "SCSI") {
                $SCSI = $true
            }
            if ($controllerType -eq "IDE") {
                $IDE = $true
            }

            $diskArgs = $rValue.Split(',')

            if ($diskArgs.Length -ne 3) {
                LogErr "Incorrect number of disk arguments: $p"
                return $False
            }

            $controllerID = $diskArgs[0].Trim()
            $lun = $diskArgs[1].Trim()
            $vhdType = $diskArgs[2].Trim()

            if ($vhdType -ne "Diff") {
                LogErr "The differencing disk test requires a differencing disk"
                return $False
            }
        }
    }

    # Make sure we have all the parameters
    if (-not $controllerType) {
        LogErr "No controller type specified in the test parameters"
        return $False
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
    if (-not $rootDir) {
        LogErr "no rootdir was specified"
    } else {
        Set-Location $rootDir
    }

    $vmGeneration = Get-VMGeneration $vmName $hvServer
    if ( $controllerType -eq "IDE" -and $vmGeneration -eq 2 ) {
        LogMsg "Generation 2 VM does not support IDE disk, please skip this case in the test script"
        return $True
    }
    #
    # Delete the drive if it exists
    #
    if($IDE) {
        $controller = Get-VMIdeController -VMName $vmName -ComputerName $hvServer `
            -ControllerNumber $controllerID
    }
    if($SCSI) {
        $controller = Get-VMScsiController -VMName $vmName -ComputerName $hvServer `
            -ControllerNumber $controllerID
    }

    if ($vmGeneration -eq 1) {
        $lun = [int]($diskArgs[1].Trim())
    } else {
        $lun = [int]($diskArgs[1].Trim()) +1
    }
    if ($controller) {
        $drive = Get-VMHardDiskDrive $controller -ControllerLocation $lun
        if ($drive) {
            LogErr "Removing $controllerType $controllerID $lun"
            Remove-VMHardDiskDrive $drive
        } else {
            LogMsg "Drive $controllerType $controllerID,$Lun does not exist"
        }
    } else {
        LogMsg "the controller $controllerType $controllerID does not exist"
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
    
    $vhdName = ("{0}{1}-{2}-{3}-{4}-Diff.{5}" `
        -f @($defaultVhdPath, $vmName, $controllerType, $controllerID, $lun, $vhdFormat))

    $vhdFileInfo = Get-RemoteFileInfo $vhdName $hvServer
    if ($vhdFileInfo) {
        $delSts = $vhdFileInfo.Delete()
        if (-not $delSts -or $delSts.ReturnValue -ne 0) {
            LogErr "unable to delete the existing $vhdFormat file: ${vhdFilename}"
            return $False
        }
    }

    # Delete ParentVHD if it was created by us
    if (-not $parentVhd) {
        $parentVhdName = $defaultVhdPath + $vmName + "_Parent." + $vhdFormat
        $parentVhdFileInfo = Get-RemoteFileInfo $parentVhdName  $hvServer
        if ($parentVhdFileInfo) {
            $delSts = $parentVhdFileInfo.Delete()
            if (-not $delSts -or $delSts.ReturnValue -ne 0) {
                LogErr "unable to delete the existing $vhdFormat file: ${parentVhdFilename}"
                return $False
            }
        }
    }

    return $True
}

Main -VMName $AllVMData.RoleName -hvServer $xmlConfig.config.Hyperv.Hosts.ChildNodes[0].ServerName `
         -TestParams $TestParams
