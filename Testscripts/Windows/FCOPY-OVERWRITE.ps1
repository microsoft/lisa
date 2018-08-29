# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Synopsis
    This script tests the file copy from host to guest overwrite functionality.

.Description
    The script will copy a text file from a Windows host to the Linux VM,
    and checks if the size and content are correct.
	Then it modifies the content of the file to a smaller size on host,
    and then copy it to the VM again, with parameter -Force, to overwrite
    the file, and then check if the size and content are correct.


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

$retVal = "FAIL"
$testfile = $null
$gsi = $null


#######################################################################
#
#	Main body script
#
#######################################################################

cd $RootDir


# if host build number lower than 9600, skip test
$BuildNumber = Get-HostBuildNumber -hvServer $HvServer
if ($BuildNumber -eq 0)
{
    return $false
}
elseif ($BuildNumber -lt 9600)
{
    return $Skipped
}



$retVal = "PASS"

#
# Verify if the Guest services are enabled for this VM
#
$gsi = Get-VMIntegrationService -vmName $VMName -ComputerName $HvServer -Name "Guest Service Interface"
if (-not $gsi) {
    LogErr "Error: Unable to retrieve Integration Service status from VM '${vmName}'" 
    return "Aborted"
}

if (-not $gsi.Enabled) {
    LogMsg "Warning: The Guest services are not enabled for VM '${vmName}'" 
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

	# Waiting for the VM to run again and respond to SSH - port 22
	do {
		sleep 5
	} until (Test-NetConnection $Ipv4 -Port 22 -WarningAction SilentlyContinue | ? { $_.TcpTestSucceeded } )
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
$sts = Check-FcopyDaemon  -vmPassword $VMPassword -VmPort $VMPort -vmUserName $VMUserName -ipv4 $Ipv4
if (-not $sts[-1]) {
   LogErr "ERROR: file copy daemon is not running inside the Linux guest VM!" 
   return"FAIL"
}

# Define the file-name to use with the current time-stamp
$testfile = "testfile-$(get-date -uformat '%H-%M-%S-%Y-%m-%d').file"

# Removing previous test files on the VM
.\Tools\plink.exe -C -pw $VMPassword -P $VMPort $VMUserName@$Ipv4 "rm -f /tmp/testfile-*"

#
# Initial file copy, which must be successful. Create a text file with 20 characters, and then copy it.
#
$vhd_path = Get-VMHost -ComputerName $HvServer | Select -ExpandProperty VirtualHardDiskPath

# Fix path format if it's broken
if ($vhd_path.Substring($vhd_path.Length - 1, 1) -ne "\"){
    $vhd_path = $vhd_path + "\"
}

$vhd_path_formatted = $vhd_path.Replace(':','$')

$filePath = $vhd_path + $testfile
$file_path_formatted = $vhd_path_formatted + $testfile

$sts = Copy-Check-File -vmUserName $VMUserName -vmPassword $VMPassword -ipv4 $Ipv4 -vmPort $VMPort -vmName $VMName -hvServer $HvServer  -testfile $testfile -overwrite $False -contentlength 20 -filePath $filePath -vhd_path_formatted $vhd_path_formatted
if (-not $sts) {
    LogErr "FAIL to initially copy the file '${testfile}' to the VM." 
    return"FAIL"
}
else {
    LogMsg "Info: The file has been initially copied to the VM '${vmName}'." 
}

#
# Second copy file overwrites the initial file. Re-write the text file with 15 characters, and then copy it with -Force parameter.
#
$sts = Copy-Check-File -vmUserName $VMUserName -vmPassword $VMPassword -ipv4 $Ipv4 -vmPort $VMPort -vmName $VMName -hvServer $HvServer -testfile $testfile -overwrite $True -contentlength 15 -filePath $filePath -vhd_path_formatted $vhd_path_formatted
if (-not $sts[-1]) {
    LogErr "FAIL to overwrite the file '${testfile}' to the VM." 
    return"FAIL"
}
else {
    LogMsg "Info: The file has been overwritten to the VM '${vmName}'." 
}

# Removing the temporary test file
Remove-Item -Path \\$HvServer\$file_path_formatted -Force
if ($? -ne "True") {
    LogErr "Cannot remove the test file '${testfile}'!" 
}

return $retVal
}

Main -VMName $AllVMData.RoleName -HvServer $xmlConfig.config.Hyperv.Host.ServerName `
         -Ipv4 $AllVMData.PublicIP -VMPort $AllVMData.SSHPort `
         -VMUserName $user -vmPassword $password -RootDir $WorkingDirectory `
         -TestParams $TestParams
