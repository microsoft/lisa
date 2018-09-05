# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.


<#
.Synopsis
    This script tests the functionality of copying a 3GB large file multiple times.
.Description
    The script will copy a random generated 2GB file multiple times from a Windows host to
    the Linux VM, and then checks if the size is matching.

#>
param([String] $TestParams)

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

$testfile = $null
$gsi = $null
#######################################################################
#
#   Main body script
#
#######################################################################
# Change the working directory for the log files
Set-Location $RootDir
# if host build number lower than 9600, skip test
$BuildNumber = Get-HostBuildNumber  -hvServer $HvServer
if ($BuildNumber -eq 0)
{
    return "FAIL"
}
elseif ($BuildNumber -lt 9600)
{
    return "ABORTED"
}

#
# Verify if the Guest services are enabled for this VM
#
$originalFileSize = $fileSize
$fileSize = $fileSize/1

$gsi = Get-VMIntegrationService -vmName $VMName -ComputerName $HvServer -Name "Guest Service Interface"
if (-not $gsi) {
    LogErr "Unable to retrieve Integration Service status from VM '${vmName}'"
    return "ABORTED"
}

if (-not $gsi.Enabled) {
    LogWarn "The Guest services are not enabled for VM '${vmName}'"
	if ((Get-VM -ComputerName $HvServer -Name $VMName).State -ne "Off") {
		Stop-VM -ComputerName $HvServer -Name $VMName -Force -Confirm:$false
	}
	# Waiting until the VM is off
	while ((Get-VM -ComputerName $HvServer -Name $VMName).State -ne "Off") {
        LogMsg "Turning off VM:'${vmName}'"
        Start-Sleep -Seconds 5
	}
    LogMsg "Enabling  Guest services on VM:'${vmName}'"
    Enable-VMIntegrationService -Name "Guest Service Interface" -vmName $VMName -ComputerName $HvServer
    LogMsg "Starting VM:'${vmName}'"
	Start-VM -Name $VMName -ComputerName $HvServer
	# Waiting for the VM to run again and respond
	do {
		Start-Sleep -Seconds 5
	} until (Test-NetConnection $Ipv4 -Port $VMPort -WarningAction SilentlyContinue | Where-Object { $_.TcpTestSucceeded } )
}
# Get VHD path of tested server; file will be copied there
$vhd_path = Get-VMHost -ComputerName $HvServer | Select-Object -ExpandProperty VirtualHardDiskPath
# Fix path format if it's broken
if ($vhd_path.Substring($vhd_path.Length - 1, 1) -ne "\"){
    $vhd_path = $vhd_path + "\"
}
$vhd_path_formatted = $vhd_path.Replace(':','$')
# Define the file-name to use with the current time-stamp
$testfile = "testfile-$(get-date -uformat '%H-%M-%S-%Y-%m-%d').file"
$filePath = $vhd_path + $testfile
$file_path_formatted = $vhd_path_formatted + $testfile

if ($gsi.OperationalStatus -ne "OK") {
   LogErr "The Guest services are not working properly for VM '${vmName}'!"
    return "FAIL"
}
else {
    # Create a sample file
    $createfile = fsutil file createnew \\$HvServer\$file_path_formatted $fileSize

    if ($createfile -notlike "File *testfile-*.file is created") {
       LogErr "Could not create the sample test file in the working directory!"
        return "FAIL"
    }
}

# Verifying if /tmp folder on guest exists; if not, it will be created
.\Tools\plink.exe -C -pw $VMPassword -P $VMPort $VMUserName@$Ipv4 "[ -d /tmp ]"
if (-not $?){
    LogMsg "Folder /tmp not present on guest. It will be created"
    .\Tools\plink.exe -C -pw $VMPassword -P $VMPort $VMUserName@$Ipv4 "mkdir /tmp"
}

#
# The fcopy daemon must be running on the Linux guest VM
#

$sts = Check-FcopyDaemon -vmPassword $VMPassword -VmPort $VMPort -vmUserName $VMUserName -ipv4 $Ipv4
if (-not $sts[-1]) {
    LogErr "File copy daemon is not running inside the Linux guest VM!"
    return "FAIL"
}

$sts = Mount-disk -vmPassword $VMPassword -vmPort $VMPort -ipv4 $Ipv4
if (-not $sts[-1]) {
    LogErr "FAIL to mount the disk in the VM."
    return "FAIL"
}

#
# Run the test
#
        $sts = Copy-FileVM -vmName $VMName -hvServer $HvServer  -filePath $filePath
        if (-not $sts) {
            LogErr "File could not be copied!"
            return "FAIL"
            break
        }
        LogMsg "File has been successfully copied to guest VM '${vmName}'"

        $sts = Check-FileInLinuxGuest  -vmPassword $VMPassword -vmPort $VMPort -vmUserName $VMUserName -ipv4 $Ipv4   -fileName "/mnt/$testfile" -checkSize $true
        if (-not $sts) {
            LogErr "File check error on the guest VM '${vmName}'!"
            return "FAIL"
            break
        }
        LogMsg "The file copied matches the ${originalFileSize} size."

        $sts = Remove-FileVM -vmPassword $VMPassword -vmPort $VMPort -ipv4 $Ipv4 -testfile $filePath
        if (-not $sts) {
            LogErr "FAIL to remove file from VM $VMName."
            return  "FAIL"
            break
        }
        LogMsg "File has been successfully removed from guest VM '${vmName}'"
#
# Removing the temporary test file
#
Remove-Item -Path \\$HvServer\$file_path_formatted -Force
if (-not $?) {
    LogErr "Cannot remove the test file '${testfile}'!"
    return "FAIL"
}
}
Main -VMName $AllVMData.RoleName -HvServer $xmlConfig.config.Hyperv.Host.ServerName `
         -Ipv4 $AllVMData.PublicIP -VMPort $AllVMData.SSHPort `
         -VMUserName $user -VMPassword $password -RootDir $WorkingDirectory `
         -TestParams $TestParams
