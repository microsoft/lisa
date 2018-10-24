# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Synopsis
    This test script will dettach VHDx disk(s) from VM and reattach them while vm is running.

.Description
    The first .vhdx file will be dettached, then the second .vhdx.
    The VM should not have attached disks anymore.
    Then the first .vhdx will be attached back, and then the second .vhdx.
    The VM should recognize the disks attached.
    Will do add/remove two disks based on LoopCount parameter.
#>

param([string] $vmName, [string] $hvServer, [string] $testParams)

function Add-VHDxDiskDrive {
    param (
        [string] $vmName, 
        [string] $hvServer,
        [string] $vhdxPath, 
        [string] $controllerType,
        [string] $controllerID,
        [string] $lun
    )
    
    $error.Clear()
    Add-VMHardDiskDrive -VMName $vmName `
                        -ComputerName $hvServer `
                        -Path $vhdxPath `
                        -ControllerType $controllerType `
                        -ControllerNumber $controllerID `
                        -ControllerLocation $lun
    if ($error.Count -gt 0) {
        LogErr "Add-VMHardDiskDrive failed to add drive on SCSI controller $error[0].Exception"
        return $False
    }
    return $True
}

function Remove-VHDxDiskDrive {
    param (
        [string] $vmName,
        [string] $hvServer,
        [string] $controllerType,
        [string] $controllerID,
        [string] $lun
    )
    
    Remove-VMHardDiskDrive -VMName $vmName `
                           -ComputerName $hvServer `
                           -ControllerType $controllerType `
                           -ControllerLocation $lun `
                           -ControllerNumber $controllerID
    if ($error.Count -gt 0) {
        LogErr "Remove-VMHardDiskDrive failed to remove drive on SCSI controller $error[0].Exception"
        return $False
    }
    return $True
}

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
    
    $scsi=$true
    $REMOTE_SCRIPT="STORAGE-HotRemove.sh"
    $rootUser="root"

    if ($null -eq $testParams -or $testParams.Length -lt 3) {
        LogErr "setupScript requires test params"
        return "FAIL"
    }

    # Parse the testParams string
    $params = $TestParams.Split(";")

    foreach ($p in $params) {
        $fields = $p.Split("=")
        switch ($fields[0].Trim()) {
            "LoopCount" { $loopCount = $fields[1].Trim() }
            default     {}  # unknown param - just ignore it
        }
    }

    if (-not (Test-Path $rootDir)) {
        LogErr "The directory `"${rootDir}`" does not exist"
        return "FAIL"
    } else {
        Set-Location $rootDir
    }

    foreach ($p in $params){
        $fields = $p.Split("=")
        $controller = $fields[0].Trim()
        if ("SCSI" -notcontains $controller) {
            # Not a test parameter we are concerned with
            continue
        }

        $controllerType=$controller
        $diskArgs = $fields[1].Trim().Split(',')
        if ($diskArgs.Length -lt 3 -or $diskArgs.Length -gt 5) {
            LogErr "Incorrect number of arguments: $p"
            return "FAIL"
        }
        $vmGeneration = Get-VMGeneration $vmName $hvServer
        if($scsi){
            $controllerID1 = $diskArgs[0].Trim()
            if ($vmGeneration -eq 1) {
                $lun1 = [int]($diskArgs[1].Trim())
            } else {
                $lun1 = [int]($diskArgs[1].Trim()) +1
            }
            $scsi=$false
        }
    }

    $path1=(Get-VMHardDiskDrive -VMName $vmName -ComputerName $hvServer -ControllerLocation $lun1 `
                -ControllerNumber $controllerID1 -ControllerType $controllerType).Path

    for ($i=0; $i -lt $loopCount; $i++) {
        #Remove the 1st VHDx
        LogMsg "Current loop number is $i."
        $retVal = Remove-VHDxDiskDrive $vmName $hvServer $controllerType $controllerID1 $lun1
        if (-not $retVal[-1]) {
            LogErr "Failed to remove first VHDx with path $path1!"
            return "FAIL"
        }
        LogMsg "Removed first VHDx with path $path1"

        #verify if vm sees that disks were dettached
        $retVal = RunLinuxCmd -username $VMUserName -password $VMPassword -ip $Ipv4 -port $VMPort `
            -command "bash ~/${REMOTE_SCRIPT}"

        #Attaching the 1st VHDx again
        $retVal = Add-VHDxDiskDrive $vmName $hvServer $path1 $controllerType $controllerID1 $lun1
        if (-not $retVal[-1]) {
            LogErr "Failed to attach first VHDx with path $path1!"
            return "FAIL"
        }
        LogErr "Attached first VHDx with path $path1"
        #wait for vm to see the disks
        Start-Sleep 5
        $diskNumber = RunLinuxCmd -username $rootUser -password $VMPassword -ip $Ipv4 -port $VMPort `
            -command "fdisk -l | grep 'Disk /dev/sd*' | grep -v 'Disk /dev/sda' | wc -l"
        if ( $diskNumber -ne 2) {
            LogErr "Failed to attach VHDx "
            return "FAIL"
        }
    }

    return "PASS"
}

Main -VMname $AllVMData.RoleName -HvServer $xmlConfig.config.Hyperv.Hosts.ChildNodes[0].ServerName `
    -Ipv4 $AllVMData.PublicIP -VMPort $AllVMData.SSHPort `
    -VMUserName $user -VMPassword $password -RootDir $WorkingDirectory `
    -TestParams $TestParams


