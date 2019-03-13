# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Synopsis
    This script tests the functionality of copying a large file.

.Description
    The script will copy a random generated file from a Windows host to
	the Linux VM, and then checks if the size is matching.


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

$testfile = $null
$gsi = $null
# Default 10GB file size
$filesize = 10737418240
#######################################################################
#
#	Main body script
#
#######################################################################

Set-Location $RootDir
# if host build number lower than 9600, skip test
$BuildNumber = Get-HostBuildNumber -hvServer $HvServer
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
$gsi = Get-VMIntegrationService -vmName $VMName -ComputerName $HvServer -Name "Guest Service Interface"
if (-not $gsi) {
    Write-LogErr "Unable to retrieve Integration Service status from VM '${vmName}'"
    return "ABORTED"
}

if (-not $gsi.Enabled) {
    Write-LogWarn "The Guest services are not enabled for VM '${vmName}'"
	if ((Get-VM -ComputerName $HvServer -Name $VMName).State -ne "Off") {
		Stop-VM -ComputerName $HvServer -Name $VMName -Force -Confirm:$false
	}

	# Waiting until the VM is off
	while ((Get-VM -ComputerName $HvServer -Name $VMName).State -ne "Off") {
        Write-LogInfo "Turning off VM:'${vmName}'"
        Start-Sleep -Seconds 5
	}
    Write-LogInfo "Enabling  Guest services on VM:'${vmName}'"
    Enable-VMIntegrationService -Name "Guest Service Interface" -vmName $VMName -ComputerName $HvServer
    Write-LogInfo "Starting VM:'${vmName}'"
	Start-VM -Name $VMName -ComputerName $HvServer

	# Waiting for the VM to run again and respond
	do {
		Start-Sleep -Seconds 5
	} until (Test-NetConnection $Ipv4 -Port $VMPort -WarningAction SilentlyContinue | Where-Object { $_.TcpTestSucceeded } )
}

if ($gsi.OperationalStatus -ne "OK") {
	Write-LogErr "The Guest services are not working properly for VM '${vmName}'!"
	return  "FAIL"
}
#
# The fcopy daemon must be running on the Linux guest VM
#
$sts = Check-FcopyDaemon  -vmPassword $VMPassword -VmPort $VMPort -vmUserName $VMUserName -ipv4 $Ipv4
if (-not $sts[-1]) {
	 Write-LogErr "File copy daemon is not running inside the Linux guest VM!"
	 return  "FAIL"
 }
# Get VHD path of tested server; file will be copied there
$vhd_path = Get-VMHost -ComputerName $HvServer | Select-Object -ExpandProperty VirtualHardDiskPath
# Fix path format if it's broken
if ($vhd_path.Substring($vhd_path.Length - 1, 1) -ne "\"){
    $vhd_path = $vhd_path + "\"
}

$vhd_path_formatted = $vhd_path.Replace(':','$')

# Define the file-name to use with the current time-stamp
$testfile = "testfile-$(Get-Date -uformat '%H-%M-%S-%Y-%m-%d').file"

$filePath = $vhd_path + $testfile
$file_path_formatted = $vhd_path_formatted + $testfile

# Create a sample big file
$createfile = fsutil file createnew \\$HvServer\$file_path_formatted $filesize

if ($createfile -notlike "File *testfile-*.file is created") {
	Write-LogErr "Could not create the sample test file in the working directory!"
	return "FAIL"
}

$sts = Mount-Disk -vmUsername $VMUserName -vmPassword $VMPassword -vmPort $VMPort -ipv4 $Ipv4
if (-not $sts) {
    Write-LogErr "FAIL to mount the disk in the VM."
    return "FAIL"
}
#
# Copy the file to the Linux guest VM
#

$Error.Clear()
$copyDuration = (Measure-Command { Copy-VMFile -vmName $VMName -ComputerName $HvServer -SourcePath $filePath -DestinationPath `
    "/mnt/test/" -FileSource Host }).totalseconds
if ($Error.Count -eq 0) {
	Write-LogInfo "File has been successfully copied to guest VM '${vmName}'"
}
else {
	Write-LogErr "File could not be copied!"
	return "FAIL"
}

[int]$copyDuration = [math]::floor($copyDuration)

Write-LogInfo "The file copy process took ${copyDuration} seconds"

#
# Checking if the file is present on the guest and file size is matching
#
$sts = Check-FileInLinuxGuest -vmUserName $VMUserName -vmPassword $VMPassword -vmPort $VMPort -ipv4 $Ipv4 -fileName "/mnt/test/$testfile"  -checkSize $True
if  (-not $sts) {
	Write-LogInfo "File is not present on the guest VM '${vmName}'!"
	return "FAIL"
}
elseif ($sts -eq $filesize) {
    Write-LogInfo "The file copied matches the size: $filesize bytes."
    return "PASS"
}
else {
	Write-LogErr "The file copied doesn't match the size: $filesize bytes!"
	return "FAIL"
}
#
# Removing the temporary test file
#
Remove-Item -Path \\$HvServer\$file_path_formatted -Force
if (-not $?) {
    Write-LogErr "ERROR: Cannot remove the test file '${testfile}'!"
    return "FAIL"
}
}

Main -VMName $AllVMData.RoleName -HvServer $GlobalConfig.Global.Hyperv.Hosts.ChildNodes[0].ServerName `
         -Ipv4 $AllVMData.PublicIP -VMPort $AllVMData.SSHPort `
         -VMUserName $user -VMPassword $password -RootDir $WorkingDirectory `
         -TestParams $TestParams
