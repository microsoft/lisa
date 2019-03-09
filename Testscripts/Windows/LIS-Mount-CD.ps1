# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Synopsis
    Mount an ISO file in the VM default DVD drive.

.Description
    Mount a .iso in the default DVD drive.
#>

param([String] $TestParams,
      [object] $AllVmData)

function Main {
    param (
        $VMName,
        $HvServer,
        $RootDir,
        $TestParams
    )
    # any small ISO file URL can be used
    # using a PowerPC ISO, which does not boot on Gen1/Gen2 VMs
    # For other bootable media must ensure that boot from CD is not the first option
    $url = "http://ports.ubuntu.com/dists/trusty/main/installer-powerpc/current/images/powerpc/netboot/mini.iso"
    $hotAdd = "$False"
    #######################################################################
    #
    # Main script body
    #
    #######################################################################
    # Check arguments
    if (-not $VMName) {
       Write-LogErr "Missing vmName argument"
        return $False
    }

    if (-not $HvServer) {
       Write-LogErr  "Missing hvServer argument"
        return $False
    }
    #
    # Extract the testParams
    #
    $params = $TestParams.Split(';')
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

        if ($lValue -eq "HotAdd") {
            $hotAdd = $rValue
        }
    }

    $error.Clear()

    $vmGen = Get-VMGeneration  -vmName  $VMName -hvServer $HvServer
    if ( $hotAdd -eq "True" -and $vmGen -eq 1) {
       Write-LogInfo " Generation 1 VM does not support hot add DVD, please skip this case in the test script"
        return $True
    }

    #
    # There should be only one DVD unit by default
    #
    $dvd = Get-VMDvdDrive $VMName -ComputerName $HvServer
    if ( $dvd ) {
        try {
            Remove-VMDvdDrive $dvd -Confirm:$False
        }
        catch {
            Write-LogErr "Cannot remove DVD drive from ${vmName}"
            $error[0].Exception
            return $False
        }
    }

    #
    # Get Hyper-V VHD path
    #
    $obj = Get-WmiObject -ComputerName $HvServer -Namespace "root\virtualization\v2" -Class "MsVM_VirtualSystemManagementServiceSettingData"
    $defaultVhdPath = $obj.DefaultVirtualHardDiskPath
    if (-not $defaultVhdPath) {
        Write-LogErr "Unable to determine VhdDefaultPath on Hyper-V server ${hvServer}"
        $error[0].Exception
        return $False
    }
    if (-not $defaultVhdPath.EndsWith("\")) {
        $defaultVhdPath += "\"
    }
    $isoPath = $defaultVhdPath + "${vmName}_CDtest.iso"

    $WebClient = New-Object System.Net.WebClient
    $WebClient.DownloadFile("$url", "$isoPath")

    try {
        Get-RemoteFileInfo -filename $isoPath  -server $HvServer
    }
    catch {
        Write-LogErr "The .iso file $isoPath could not be found!"
        return $False
    }

    #
    # Insert the .iso file into the VMs DVD drive
    #
    if ($vmGen -eq 1) {
        Add-VMDvdDrive -VMName $VMName -Path $isoPath -ControllerNumber 1 -ControllerLocation 1 -ComputerName $HvServer -Confirm:$False
    }
    else {
        Add-VMDvdDrive -VMName $VMName -Path $isoPath -ControllerNumber 0 -ControllerLocation 1 -ComputerName $HvServer -Confirm:$False
    }

    if ($? -ne "True") {
        Write-LogErr "Unable to mount the ISO file!"
        $error[0].Exception
        return $False
    }
    else {
        $retVal = $True
    }

    return $retVal
}
Main -VMName $AllVMData.RoleName -HvServer $GlobalConfig.Global.Hyperv.Hosts.ChildNodes[0].ServerName `
    -RootDir $WorkingDirectory  -TestParams $TestParams `
