# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.


<#
.Synopsis
    This script tests the file copy functionality.

.Description
    The script will generate a 100MB file with non-ascii characters. Then
    it will copy the file to the Linux VM. Finally, the script will verify
    both checksums (on host and guest).

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
#######################################################################
#
# Main script body
#
#######################################################################
# Change the working directory to where we need to be
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
    LogErr "Unable to retrieve Integration Service status from VM '${vmName}'" 
    return "ABORTED"
}

if (-not $gsi.Enabled) {
    LogWarn "Warning: The Guest services are not enabled for VM '${vmName}'" 
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
		Start-Sleep -Seconds 5
	} until (Test-NetConnection $Ipv4 -Port 22 -WarningAction SilentlyContinue | Where-Object { $_.TcpTestSucceeded } )
}

# Check to see if the fcopy daemon is running on the VM
$sts = Check-FcopyDaemon  -vmPassword $VMPassword -VmPort $VMPort -vmUserName $VMUserName -ipv4 $Ipv4
if (-not $sts[-1]) {
	 LogErr "File copy daemon is not running inside the Linux guest VM!" 
	 return "FAIL"
	exit 1
}
#
# Creating the test file for sending on VM
#
if ($gsi.OperationalStatus -ne "OK") {
   LogErr "The Guest services are not working properly for VM '${vmName}'!" 
   return  "FAIL"
}
else {
    # Define the file-name to use with the current time-stamp
    $CurrentDir= "$pwd\"
    $testfile = "testfile-$(get-date -uformat '%H-%M-%S-%Y-%m-%d').file"
    $pathToFile="$CurrentDir"+"$testfile"

    # Sample string with non-ascii chars
    $nonAsciiChars="¡¢£¤¥§¨©ª«¬®¡¢£¤¥§¨©ª«¬®¯±µ¶←↑ψχφυ¯±µ¶←↑ψ¶←↑ψχφυ¯±µ¶←↑ψχφυχφυ"

    # Create a ~2MB sample file with non-ascii characters
    $stream = [System.IO.StreamWriter] $pathToFile
    1..8000 | ForEach-Object {
        $stream.WriteLine($nonAsciiChars)
    }
    $stream.close()

    # Checking if sample file was successfully created
    if (-not $?){
        LogErr "Unable to create the 2MB sample file" 
        return "FAIL"
    }
    else {
        LogMsg "Info: initial 2MB sample file $testfile successfully created"
    }

    # Multiply the contents of the sample file up to an 100MB auxiliary file
    New-Item $MyDir"auxFile" -type file | Out-Null
    2..130| ForEach-Object {
        $testfileContent = Get-Content $pathToFile
        Add-Content $MyDir"auxFile" $testfileContent
    }

    # Checking if auxiliary file was successfully created
    if (-not $?){
        LogErr " Unable to create the extended auxiliary file!" 
        return "FAIL"
    }

    # Move the auxiliary file to testfile
    Move-Item -Path $MyDir"auxFile" -Destination $pathToFile -Force

    # Checking file size. It must be over 85MB
    $testfileSize = (Get-Item $pathToFile).Length
    if ($testfileSize -le 85mb) {
        LogErr "File not big enough. File size: $testfileSize MB" 
        $testfileSize = $testfileSize / 1MB
        $testfileSize = [math]::round($testfileSize,2)
        LogErr "File not big enough (over 85MB)! File size: $testfileSize MB" 
        RemoveTestFile -pathToFile $pathToFile -tesfile $testfile
        return "FAIL"
    }
    else {
        $testfileSize = $testfileSize / 1MB
        $testfileSize = [math]::round($testfileSize,2)
		LogMsg "Info: $testfileSize MB auxiliary file successfully created"
    }

    # Getting MD5 checksum of the file
    $local_chksum = Get-FileHash .\$testfile -Algorithm MD5 | Select-Object -ExpandProperty hash
    if (-not $?){
       LogErr "Unable to get MD5 checksum!" 
       RemoveTestFile -pathToFile $pathToFile -tesfile $testfile
        return "FAIL"
    }
    else {
        LogMsg "MD5 file checksum on the host-side: $local_chksum"
        return "PASS"
    }

    # Get vhd folder
    $vhd_path = Get-VMHost -ComputerName $HvServer | Select-Object -ExpandProperty VirtualHardDiskPath

    # Fix path format if it's broken
    if ($vhd_path.Substring($vhd_path.Length - 1, 1) -ne "\"){
        $vhd_path = $vhd_path + "\"
    }

    $vhd_path_formatted = $vhd_path.Replace(':','$')

    $filePath = $vhd_path + $testfile
    $file_path_formatted = $vhd_path_formatted + $testfile

    # Copy file to vhd folder
    Copy-Item -Path .\$testfile -Destination \\$HvServer\$vhd_path_formatted
}

# Removing previous test files on the VM
.\Tools\plink.exe -C -pw $VMPassword -P $VMPort $VMUserName@$Ipv4 "rm -f /tmp/testfile-*"

#
# Sending the test file to VM
#
$Error.Clear()
Copy-VMFile -vmName $VMName -ComputerName $HvServer -SourcePath $filePath -DestinationPath "/tmp/" `
 -FileSource host -ErrorAction SilentlyContinue
if ($Error.Count -eq 0) {
    LogMsg "File has been successfully copied to guest VM '${vmName}'" 
    return "PASS"
}
elseif (($Error.Count -gt 0) -and ($Error[0].Exception.Message  `
 -like "*FAIL to initiate copying files to the guest: The file exists. (0x80070050)*")) {
    LogErr "Test FAIL! File could not be copied as it already exists on guest VM '${vmName}'" 
    return "FAIL"
}
Remove-TestFile -pathToFile $pathToFile -tesfile $testfile

#
# Verify if the file is present on the guest VM
#
.\Tools\plink.exe -C -pw $VMPassword -P $VMPort $VMUserName@$Ipv4 "stat /tmp/testfile-* > /dev/null" 2> $null
if (-not $?) {
	LogErr "Test file is not present on the guest VM!" 
	return "FAIL"
}

#
# Verify if the file is present on the guest VM
#
$remote_chksum=.\Tools\plink.exe -C -pw $VMPassword -P $VMPort $VMUserName@$Ipv4 "openssl MD5 /tmp/testfile-* | cut -f2 -d' '"
if (-not $?) {
	LogErr "Could not extract the MD5 checksum from the VM!" 
	return "FAIL"
}

LogMsg "MD5 file checksum on guest VM: $remote_chksum" 

#
# Check if checksums are matching
#
$MD5IsMatching = @(Compare-Object $local_chksum $remote_chksum -SyncWindow 0).Length -eq 0
if ( -not $MD5IsMatching) {
    LogErr "MD5 checksum missmatch between host and VM test file!" 
    return "FAIL"
}

LogMsg "Info: MD5 checksums are matching between the host-side and guest VM file." 

# Removing the temporary test file
Remove-Item -Path \\$HvServer\$file_path_formatted -Force
if ($? -ne "True") {
    LogErr "Cannot remove the test file '${testfile}'!" 
	return "FAIL"
}
#
# If we made it here, everything worked
#
LogMsg "Test completed successfully"
return "PASS"
}

Main -VMName $AllVMData.RoleName -HvServer $xmlConfig.config.Hyperv.Host.ServerName `
         -Ipv4 $AllVMData.PublicIP -VMPort $AllVMData.SSHPort `
         -VMUserName $user -VMPassword $password -RootDir $WorkingDirectory `
         -TestParams $TestParams
