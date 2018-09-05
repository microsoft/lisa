# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.


<#
.Synopsis
    This script tests the file copy functionality.

.Description
    The script will copy a random generated 10MB file from a Windows host to
	the Linux VM, and then checks if the size is matching.


#>
param([String] $TestParams)

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


    $testfile = "$null"
    $gsi = "$null"
    #######################################################################
    #
    #	Main body script
    #
    #######################################################################
    Set-Location $rootDir
    # if host build number lower than 9600, skip test
    $BuildNumber = Get-HostBuildNumber -HvServer $HvServer
    if ($BuildNumber -eq 0) {
        return "FAIL"
    }
    elseif ($BuildNumber -lt 9600) {
        return "ABORTED"
    }
    #
    # Verify if the Guest services are enabled for this VM
    #
    $gsi = Get-VMIntegrationService -VMname $VMname -ComputerName $HvServer -Name "Guest Service Interface"
    if (-not $gsi) {
        LogErr "Unable to retrieve Integration Service status from VM '${VMname}'"
        return "ABORTED"
    }
    if (-not $gsi.Enabled) {
        LogWarn "The Guest services are not enabled for VM '${VMname}'"
        if ((Get-VM -ComputerName $HvServer -Name $VMname).State -ne "Off") {
            Stop-VM -ComputerName $HvServer -Name $VMname -Force -Confirm:$false
        }
        # Waiting until the VM is off
        while ((Get-VM -ComputerName $HvServer -Name $VMname).State -ne "Off") {
            LogMsg "Turning off VM:'${VMname}'"
            Start-Sleep -Seconds 5
        }
        LogMsg "Enabling  Guest services on VM:'${VMname}'"
        Enable-VMIntegrationService -Name "Guest Service Interface" -VMname $VMname -ComputerName $HvServer
        LogMsg "Starting VM:'${VMname}'"
        Start-VM -Name $VMname -ComputerName $HvServer
        # Waiting for the VM to run again and respond
        do {
            Start-Sleep -Seconds 5
        } until (Test-NetConnection $Ipv4 -Port $VMPort -WarningAction SilentlyContinue | Where-Object { $_.TcpTestSucceeded } )
    }

    # Get VHD path of tested server; file will be copied there
    $vhd_path = Get-VMHost -ComputerName $HvServer | Select-Object -ExpandProperty VirtualHardDiskPath

    # Fix path format if it's broken
    if ($vhd_path.Substring($vhd_path.Length - 1, 1) -ne "\") {
        $vhd_path = $vhd_path + "\"
    }

    $vhd_path_formatted = $vhd_path.Replace(':', '$')

    # Define the file-name to use with the current time-stamp
    $testfile = "testfile-$(Get-Date -uformat '%H-%M-%S-%Y-%m-%d').file"

    $filePath = $vhd_path + $testfile
    $file_path_formatted = $vhd_path_formatted + $testfile


    if ($gsi.OperationalStatus -ne "OK") {
        LogErr "The Guest services are not working properly for VM '${VMname}'!"
        return "FAIL"
    }
    else {
        # Create a 10MB sample file
        $createfile = fsutil file createnew \\$HvServer\$file_path_formatted 10485760

        if ($createfile -notlike "File *testfile-*.file is created") {
            LogErr	"Could not create the sample test file in the working directory!"
            return "FAIL"
        }
    }

    # Verifying if /tmp folder on guest exists; if not, it will be created
    .\Tools\plink.exe -C -pw $VMPassword -P $VMPort $VMUserName@$Ipv4 "[ -d /tmp ]"
    if (-not $?) {
        LogMsg "Folder /tmp not present on guest. It will be created"
        .\Tools\plink.exe -C -pw $VMPassword -P $VMPort $VMUserName@$Ipv4 "mkdir /tmp"
    }

    # The fcopy daemon must be running on the Linux guest VM
    $sts = Check-FcopyDaemon  -VMPassword $VMPassword -VMPort $VMPort -VMUserName $VMUserName -Ipv4 $Ipv4
    if (-not $sts[-1]) {
        LogErr "File copy daemon is not running inside the Linux guest VM!"
        return "FAIL"
    }

    # Removing previous test files on the VM
    .\Tools\plink.exe -C -pw $VMPassword -P $VMPort $VMUserName@$Ipv4 "rm -f /tmp/testfile-*"

    # If we got here then all checks have PASS and we can copy the file to the Linux guest VM
    $Error.Clear()
    Copy-VMFile -VMname $VMname -ComputerName $HvServer -SourcePath $filePath -DestinationPath "/tmp/" -FileSource host -ErrorAction SilentlyContinue
    if ($Error.Count -eq 0) {
        LogMsg "File has been successfully copied to guest VM '${VMname}'"
        return "PASS"
    }
    elseif (($Error.Count -gt 0) -and ($Error[0].Exception.Message  `
                -like "*FAIL to initiate copying files to the guest: The file exists. (0x80070050)*")) {
        LogErr "Test FAIL! File could not be copied as it already exists on guest VM '${VMname}'"
        return "FAIL"
    }

    # Checking if the file size is matching
    $sts = Check-FileInLinuxGuest -VMPassword $VMPassword -VMPort $VMPort -VMUserName $VMUserName -Ipv4 $Ipv4 -fileName "/tmp/$testfile"
    if (-not $sts[-1]) {
        LogErr "File is not present on the guest VM '${VMname}'!"
        return "FAIL"
    }
    elseif ($sts[0] -eq 10485760) {
        LogMsg "The file copied matches the 10MB size."
        return "PASS"
    }
    else {
        LogErr " The file copied doesn't match the 10MB size!"
        return "FAIL"
    }

    # Removing the temporary test file
    Remove-Item -Path \\$HvServer\$file_path_formatted -Force
    if ($LASTEXITCODE -ne "0") {
        LogErr "Cannot remove the test file '${testfile}'!"
        return "FAIL"
    }
}

Main -VMname $AllVMData.RoleName -HvServer $xmlConfig.config.Hyperv.Host.ServerName `
    -Ipv4 $AllVMData.PublicIP -VMPort $AllVMData.SSHPort `
    -VMUserName $user -VMPassword $password -RootDir $WorkingDirectory `
    -TestParams $TestParams
