# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Synopsis
    This script tests the file copy overwrite functionality.

.Description
    The script will copy a file from a Windows host to the Linux VM,
    and checks if the size is matching.
	Then it tries to copy the same file again, which must fail with an
	error message that the file already exists - error code 0x80070050.



#>

param([String] $TestParams,
      [object] $AllVmData)
function Main {
    param (
        $VMName,
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
    Set-Location $RootDir
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
    $gsi = Get-VMIntegrationService -vmName $VMName -ComputerName $hvServer -Name "Guest Service Interface"
    if (-not $gsi) {
        Write-LogErr " Unable to retrieve Integration Service status from VM '${vmName}'"
        return "ABORTED"
    }

    if (-not $gsi.Enabled) {
        Write-LogWarn "The Guest services are not enabled for VM '${vmName}'"
        if ((Get-VM -ComputerName $hvServer -Name $VMName).State -ne "Off") {
            Stop-VM -ComputerName $hvServer -Name $VMName -Force -Confirm:$false
        }

        # Waiting until the VM is off
        while ((Get-VM -ComputerName $hvServer -Name $VMName).State -ne "Off") {
            Write-LogInfo "Turning off VM:'${vmName}'"
            Start-Sleep -Seconds 5
        }
        Write-LogInfo "Enabling  Guest services on VM:'${vmName}'"
        Enable-VMIntegrationService -Name "Guest Service Interface" -vmName $VMName -ComputerName $hvServer
        Write-LogInfo "Starting VM:'${vmName}'"
        Start-VM -Name $VMName -ComputerName $hvServer

        # Waiting for the VM to run again and respond
        do {
            Start-Sleep -Seconds 5
        } until (Test-NetConnection $Ipv4 -Port $VMPort -WarningAction SilentlyContinue | Where-Object { $_.TcpTestSucceeded } )
    }


    # Get VHD path of tested server; file will be copied there
    $vhd_path = Get-VMHost -ComputerName $hvServer | Select-Object -ExpandProperty VirtualHardDiskPath

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
        Write-LogErr "The Guest services are not working properly for VM '${vmName}'!"
        return "FAIL"
    }
    else {
        # Create a 10MB sample file
        $createfile = fsutil file createnew \\$hvServer\$file_path_formatted 10485760

        if ($createfile -notlike "File *testfile-*.file is created") {
            Write-LogErr	"Could not create the sample test file in the working directory!"
            return "FAIL"
        }
    }

    # Verifying if /tmp folder on guest exists; if not, it will be created
    .\Tools\plink.exe -C -pw $VMPassword -P $VMPort $VMUserName@$Ipv4 "[ -d /tmp ]"
    if (-not $?) {
        Write-LogInfo "Folder /tmp not present on guest. It will be created"
        .\Tools\plink.exe -C -pw $VMPassword -P $VMPort $VMUserName@$Ipv4 "mkdir /tmp"
    }
    # The fcopy daemon must be running on the Linux guest VM
    $sts = Check-FcopyDaemon  -vmPassword $VMPassword -VmPort $VMPort -vmUserName $VMUserName -ipv4 $Ipv4
    if (-not $sts[-1]) {
        Write-LogErr "File copy daemon is not running inside the Linux guest VM!"
        return "FAIL"
    }
    # Removing previous test files on the VM
    .\Tools\plink.exe -C -pw $VMPassword -P $VMPort $VMUserName@$Ipv4 "rm -f /tmp/testfile-*"

    # If we got here then all checks have PASS and we can copy the file to the Linux guest VM
    # Initial file copy, which must be successful
    $Error.Clear()
    Copy-VMFile -vmName $VMName -ComputerName $hvServer -SourcePath $filePath -DestinationPath "/tmp/" -FileSource host
    if ($error.Count -eq 0) {
        # Checking if the file size is matching
        $sts = Check-FileInLinuxGuest -vmPassword $VMPassword -vmPort $VMPort -vmUserName $VMUserName -ipv4 $Ipv4 -filename "/tmp/$testfile" -checkSize $true
        if (-not $sts) {
            Write-LogErr "File is not present on the guest VM '${vmName}'!"
            return "FAIL"
        }
        elseif ($sts -eq 10485760) {
            Write-LogInfo "Info: The file copied matches the 10MB size."
            return "PASS"
        }
        else {
            Write-LogErr "The file copied doesn't match the 10MB size!"
            return "FAIL"
        }
    }
    elseif ($Error.Count -gt 0) {
        Write-LogErr "Test FAIL. An error has occurred while copying the file to guest VM '${vmName}'!"
        $error[0]
        return "FAIL"
    }

    $Error.Clear()
    # Second copy file attempt must fail with the below error code pattern
    Copy-VMFile -vmName $VMName -ComputerName $hvServer -SourcePath $filePath -DestinationPath "/tmp/" -FileSource host -ErrorAction SilentlyContinue
    if ($error.Count -eq 0) {
        Write-LogInfo "Test PASS! File could not be copied as it already exists on guest VM '${vmName}'"
        return "PASS"
    }
    elseif ($error.Count -eq 1) {
        Write-LogErr "File '${testfile}' has been copied twice to guest VM '${vmName}'!"
        return "FAIL"
    }
    # Removing the temporary test file
    Remove-Item -Path \\$HvServer\$file_path_formatted -Force
    if ($LASTEXITCODE -ne "0") {
        Write-LogErr "cannot remove the test file '${testfile}'!"
        return "FAIL"
    }
}
Main -VMName $AllVMData.RoleName -HvServer $GlobalConfig.Global.Hyperv.Hosts.ChildNodes[0].ServerName `
    -Ipv4 $AllVMData.PublicIP -VMPort $AllVMData.SSHPort `
    -VMUserName $user -VMPassword $password -RootDir $WorkingDirectory `
    -TestParams $TestParams
