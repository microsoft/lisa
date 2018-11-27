# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Synopsis
    This setup script will run after the VM shuts down, then delete the VHD.

.Description
   This is a cleanup script that will run after the VM shuts down.
   This script will delete the hard drive, and if no other drives
   are attached to the controller, delete the controller.

   Note: The controller will not be removed if it is an IDE.
         IDE Lun 0 will not be removed.
#>

param([string] $TestParams)

function Main {
    param (
        $VMName,
        $HvServer,
        $TestParams
    )

    if ($null -eq $TestParams -or $TestParams.Length -lt 13) {
        # The minimum length testParams string is "IDE=1,1,Fixed"
        Write-LogErr "No testParams provided"
        return $False
    }

    $params = $TestParams.Split(';')
    foreach ($p in $params) {
        if ($p.Trim().Length -eq 0) {
            continue
        }

        $fields = $p.Split('=')
        if ($fields.Length -ne 2) {
            Write-LogErr "Invalid test parameter: $p"
            return $False
        }

        $field_value = $fields[0].Trim().ToLower()
        if ($field_value -ne "scsi" -and $field_value -ne "ide") {
            # Just ignore the parameter
            continue
        } else {
            $controllerType = $fields[0].Trim().ToUpper()
        }
    }

    $vhdName = $VMName + "-" + $controllerType
    $vhdDisks = Get-VMHardDiskDrive -VMName $VMName -ComputerName $hvServer
    foreach ($vhd in $vhdDisks) {
        $vhdPath = $vhd.Path
        if ($vhdPath.Contains($vhdName) -or $vhdPath.Contains('Target')){
            $error.Clear()
            Write-LogInfo "Removing drive $vhdName"

            Remove-VMHardDiskDrive -VMName $VMName -ControllerType $vhd.controllerType `
                -ControllerNumber $vhd.controllerNumber -ControllerLocation $vhd.ControllerLocation `
                -ComputerName $hvServer
            if ($error.Count -gt 0) {
                Write-LogErr "Remove-VMHardDiskDrive failed to delete drive on SCSI controller "
                return $False
            }
        }
    }

    $hostInfo = Get-VMHost -ComputerName $hvServer
    if (-not $hostInfo) {
        Write-LogErr "Unable to collect Hyper-V settings for ${hvServer}"
        return $False
    }

    $defaultVhdPath = $hostInfo.VirtualHardDiskPath
    $defaultVhdPath = $defaultVhdPath.Replace(':','$')
    if (-not $defaultVhdPath.EndsWith("\")) {
        $defaultVhdPath += "\"
    }

    Set-Item WSMan:\localhost\Client\TrustedHosts $hvServer -force
    if (-not $?) {
        Write-LogErr "Failed to add $hvServer to the trusted hosts list"
        return $False
    }

    Get-ChildItem \\$hvServer\$defaultVhdPath -Filter $vhdName* | `
        Foreach-Object  {
            $remotePath = $_.FullName
            $localPath = $remotePath.Substring($hvServer.Length + 3).Replace('$',':')
            Invoke-Command $hvServer -ScriptBlock {Dismount-VHD -Path $args[0] -ErrorAction SilentlyContinue} `
                -ArgumentList $localPath
            $error.Clear()
            Remove-Item -Path $_.FullName
            if ($error.Count -gt 0) {
                Write-LogErr "Failed to delete VHDx File "
                return $False
            }
        }

    Write-LogInfo "RemoveHardDisk returning $retVal"

    return $True
}

Main -VMName $AllVMData.RoleName -hvServer $xmlConfig.config.Hyperv.Hosts.ChildNodes[0].ServerName `
         -TestParams $TestParams
