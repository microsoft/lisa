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

	# Waiting for the VM to run again and respond to SSH - port 22
	do {
        Start-Sleep -Seconds 5
	} until (Test-NetConnection $Ipv4 -Port $VMPort -WarningAction SilentlyContinue | Where-Object { $_.TcpTestSucceeded } )
}

# Verifying if /tmp folder on guest exists; if not, it will be created
.\Tools\plink.exe -C -pw $VMPassword -P $VMPort $VMUserName@$Ipv4 "[ -d /tmp ]"
if (-not $?){
     Write-LogInfo "Folder /tmp not present on guest. It will be created"
    .\Tools\plink.exe -C -pw $VMPassword -P $VMPort $VMUserName@$Ipv4 "mkdir /tmp"
}
#
# The fcopy daemon must be running on the Linux guest VM
#
$sts = Check-FcopyDaemon  -vmPassword $VMPassword -VmPort $VMPort -vmUserName $VMUserName -ipv4 $Ipv4
if (-not $sts[-1]) {
   Write-LogErr "File copy daemon is not running inside the Linux guest VM!"
   return "FAIL"
}
# Define the file-name to use with the current time-stamp
$testfile = "testfile-$(Get-Date -uformat '%H-%M-%S-%Y-%m-%d').file"

# Removing previous test files on the VM
.\Tools\plink.exe -C -pw $VMPassword -P $VMPort $VMUserName@$Ipv4 "rm -f /tmp/testfile-*"
#
# Initial file copy, which must be successful. Create a text file with 20 characters, and then copy it.
#
$vhd_path = Get-VMHost -ComputerName $HvServer | Select-Object -ExpandProperty VirtualHardDiskPath

# Fix path format if it's broken
if ($vhd_path.Substring($vhd_path.Length - 1, 1) -ne "\"){
    $vhd_path = $vhd_path + "\"
}

$vhd_path_formatted = $vhd_path.Replace(':','$')

$filePath = $vhd_path + $testfile
$file_path_formatted = $vhd_path_formatted + $testfile

$sts = Copy-CheckFileInLinuxGuest -vmUserName $VMUserName -vmPassword $VMPassword -ipv4 $Ipv4 -vmPort $VMPort -vmName $VMName -hvServer $HvServer  -testfile $testfile -overwrite $False -contentlength 20 -filePath $filePath -vhd_path_formatted $vhd_path_formatted
if (-not $sts) {
    Write-LogErr "FAIL to initially copy the file '${testfile}' to the VM."
    return "FAIL"
}
else {
    Write-LogInfo "The file has been initially copied to the VM '${vmName}'."
    return "PASS"
}
#
# Second copy file overwrites the initial file. Re-write the text file with 15 characters, and then copy it with -Force parameter.
#
$sts = Copy-CheckFileInLinuxGuest -vmUserName $VMUserName -vmPassword $VMPassword -ipv4 $Ipv4 -vmPort $VMPort -vmName $VMName -hvServer $HvServer -testfile $testfile -overwrite $True -contentlength 15 -filePath $filePath -vhd_path_formatted $vhd_path_formatted
if (-not $sts) {
    Write-LogErr "FAIL to overwrite the file '${testfile}' to the VM."
    return "FAIL"
}
else {
    Write-LogInfo "The file has been overwritten to the VM '${vmName}'."
    return "PASS"
}

# Removing the temporary test file
Remove-Item -Path \\$HvServer\$file_path_formatted -Force
if ($? -ne "True") {
    Write-LogErr "Cannot remove the test file '${testfile}'!"
    return "FAIL"
}
}

Main -VMName $AllVMData.RoleName -HvServer $GlobalConfig.Global.Hyperv.Hosts.ChildNodes[0].ServerName `
         -Ipv4 $AllVMData.PublicIP -VMPort $AllVMData.SSHPort `
         -VMUserName $user -vmPassword $password -RootDir $WorkingDirectory `
         -TestParams $TestParams
