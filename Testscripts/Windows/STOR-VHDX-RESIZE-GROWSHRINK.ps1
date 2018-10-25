# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Synopsis
	Verify VHDx harddisk resize (grow & shrink)
.Description
	This is a PowerShell test case script that implements
	dynamic resizing of VHDX hard disk. It ensures that the
	VM detects the newly attached VHDx hard disk, creates
	partitions, filesytem, mounts partitions, detects if it
	can perform read/write operations on the newly created
	partitions and deletes partitions.
.Parameter testParams
	Test data for this test case
#>

Param([String] $TestParams)

$ErrorActionPreference = "Stop"
$testResult = "FAIL"

Function Set-HardDiskSize
{
	param ($vhdPath, $newSize, $controllerType, $vmName, $hvServer, $ip, $port)

	# for IDE & offline need to stop VM before resize
	if ( $controllerType -eq "IDE" -or $testParameters.Offline -eq "True") {
		LogMsg "Stopping VM for IDE disk or offline is requested"
		Stop-VM -VMName $vmName -ComputerName $hvServer -force
	}

	$newVhdxSize = Convert-StringToUInt64 $newSize
	Resize-VHD -Path $vhdPath -SizeBytes ($newVhdxSize) -ComputerName $hvServer
	if (-not $?) {
		$testResult = "FAIL"
		Throw "Unable to grow VHDX file ${vhdPath}"
	}

	# Now start the VM for IDE or Offline
	if ( $controllerType -eq "IDE" -or $testParameters.Offline -eq "True" ) {
		$timeout = 300
		Start-VM -Name $vmName -ComputerName $hvServer
		if (-not (Wait-ForVMToStartKVP $vmName $hvServer $timeout )) {
			$testResult = "FAIL"
			Throw "${vmName} failed to start"
		} else {
			LogMsg "Started VM ${vmName}"
		}
	}

	# check file size after resize
	$vhdxInfoResize = Get-VHD -Path $vhdPath -ComputerName $hvServer
	if ( $newSize.contains("GB") -and $vhdxInfoResize.Size/1gb -ne $newSize.Trim("GB") ) {
		$testResult = "FAIL"
		Throw "Failed to Resize Disk to new Size"
	}

	LogMsg "Check if the guest detects the new space"
	$sd = "sdc"
	if ( $controllerType -eq "IDE" ) {
		$sd = "sdb"
	}
	$ret = RunLinuxCmd -ip $ip -port $port -username $user -password $password -command "echo 'deviceName=/dev/$sd' >> constants.sh" -runAsSudo
	$ret = RunLinuxCmd -ip $ip -port $port -username $user -password $password -command "cp -f /home/$user/constants.sh /root/" -runAsSudo
	# Do a request & rescan to refresh the disks info
	$ret = RunLinuxCmd -ip $ip -port $port -username $user -password $password -command "fdisk -l > /dev/null" -runAsSudo
	$ret = RunLinuxCmd -ip $ip -port $port -username $user -password $password -command "echo 1 > /sys/block/$sd/device/rescan" -runAsSudo
	$diskSize = RunLinuxCmd -ip $ip -port $port -username $user -password $password -command "fdisk -l /dev/$sd  2> /dev/null | grep Disk | grep $sd | cut -f 5 -d ' '" -runAsSudo
	if (-not $diskSize) {
		$testResult = "FAIL"
		Throw "Unable to determine disk size from within the guest after growing the VHDX"
	}
	if ($diskSize -ne $newVhdxSize) {
		$testResult = "FAIL"
		Throw "VM ${vmName} detects a disk size of ${diskSize}, not the expected size of ${newVhdxSize}"
	}

	# Make sure if we can perform Read/Write operations on the guest VM
	# if file size larger than 2T (2048G), use parted to format disk
	if ([int]($newSize/1gb) -gt 2048) {
		$guestScript = "STOR_VHDXResize_PartitionDiskOver2TB.sh"
		$ret = RunLinuxCmd -ip $ip -port $port -username $user -password $password -command "cp -f /home/$user/$guestScript /root/" -runAsSudo
		$ret = RunLinuxCmd -ip $ip -port $port -username $user -password $password -command "./$guestScript" -runAsSudo -runMaxAllowedTime 1200
	} else {
		$guestScript = "STOR_VHDXResize_PartitionDisk.sh"
		$ret = RunLinuxCmd -ip $ip -port $port -username $user -password $password -command "echo 'rerun=yes' >> constants.sh" -runAsSudo
		$ret = RunLinuxCmd -ip $ip -port $port -username $user -password $password -command "cp -f /home/$user/constants.sh /root/" -runAsSudo
		$ret = RunLinuxCmd -ip $ip -port $port -username $user -password $password -command "./$guestScript" -runAsSudo
	}
	if (-not $ret) {
		$testResult = "FAIL"
		Throw "Running '${guestScript}'script failed on VM. check VM logs , exiting test case execution"
	}
	LogMsg "The guest detects the new size after resizing ($diskSize)"
} # End function

Function Main
{
	param ($vmName, $hvServer, $ip, $port)
	$resultArr = @()

	try {
		# if host build number lower than 9600, skip test
		$BuildNumber = Get-HostBuildNumber $hvServer
		if ($BuildNumber -lt 9600) {
			$testResult = "ABORTED"
			Throw "Build number less than 9600"
		}

		if ($testParameters.Contains("IDE")) {
			$controllerType = "IDE"
			$vmGeneration = Get-VMGeneration $vmName $hvServer
			if ($vmGeneration -eq 2 ) {
				$testResult = "ABORTED"
				Throw "Generation 2 VM does not support IDE disk, skip test"
			}
		}
		elseif ($testParameters.Contains("SCSI")) {
			$controllerType = "SCSI"
		}
		else {
			$testResult = "ABORTED"
			Throw "Could not determine ControllerType"
		}

		# Find the vhdx drive to operate on
		$vhdxDrive = Get-VMHardDiskDrive -VMName $vmName  -ComputerName $hvServer -ControllerLocation 1
		if (-not $vhdxDrive) {
			$testResult = "FAIL"
			Throw "No suitable virtual hard disk drives attached VM ${vmName}"
		}

		LogMsg "Check if the virtual disk file exists"
		$vhdPath = $vhdxDrive.Path
		$vhdxInfo = Get-RemoteFileInfo $vhdPath $hvServer
		if (-not $vhdxInfo) {
			$testResult = "FAIL"
			Throw "The vhdx file (${vhdPath} does not exist on server ${hvServer}"
		}

		LogMsg "Verify the file is a .vhdx"
		if (-not $vhdPath.EndsWith(".vhdx") -and -not $vhdPath.EndsWith(".avhdx")) {
			$testResult = "FAIL"
			Throw "$controllerType $vhdxDrive.ControllerNumber $vhdxDrive.ControllerLocation virtual disk is not a .vhdx file."
		}

		# Make sure there is sufficient disk space to grow the VHDX to the specified size
		$deviceID = $vhdxInfo.Drive
		$diskInfo = Get-CimInstance -Query "SELECT * FROM Win32_LogicalDisk Where DeviceID = '${deviceID}'" -ComputerName $hvServer
		if (-not $diskInfo) {
			$testResult = "FAIL"
			Throw "Unable to collect information on drive ${deviceID}"
		}
		$sizeFlag = Convert-StringToUInt64 "20GB"
		if ($diskInfo.FreeSpace -le $sizeFlag + 10MB) {
			$testResult = "FAIL"
			Throw "Insufficent disk free space, This test case requires ${testParameters.NewSize} free, Current free space is $($diskInfo.FreeSpace)"
		}

		# Copy files from home of user to home of root
		$ret = RunLinuxCmd -ip $ip -port $port -username $user -password $password -command "cp -f /home/$user/STOR_VHDXResize_ReadWrite.sh /root/" -runAsSudo
		$ret = RunLinuxCmd -ip $ip -port $port -username $user -password $password -command "cp -f /home/$user/STOR_VHDXResize_PartitionDisk.sh /root/" -runAsSudo
		$ret = RunLinuxCmd -ip $ip -port $port -username $user -password $password -command "cp -f /home/$user/check_traces.sh /root/" -runAsSudo

		# Make sure if we can perform Read/Write operations on the guest VM
		$ret = RunLinuxCmd -ip $ip -port $port -username $user -password $password -command "echo 'deviceName=/dev/sdc' >> constants.sh" -runAsSudo
		$ret = RunLinuxCmd -ip $ip -port $port -username $user -password $password -command "cp -f /home/$user/constants.sh /root/" -runAsSudo
		$ret = RunLinuxCmd -ip $ip -port $port -username $user -password $password -command "./STOR_VHDXResize_PartitionDisk.sh" -runAsSudo
		if (-not $ret) {
			$testResult = "FAIL"
			Throw "Running '${guestScript}'script failed on VM. check VM logs , exiting test case execution"
		}

		if ($null -ne $testParameters.growSize) {
			$newSize = $testParameters.growSize
			Set-HardDiskSize $vhdPath $newSize $controllerType $vmName $hvServer $ip $port
		}
		if ($null -ne $testParameters.shrinkSize) {
			$newSize = $testParameters.shrinkSize
			Set-HardDiskSize $vhdPath $newSize $controllerType $vmName $hvServer $ip $port
		}
		if ($null -ne $testParameters.newSize) {
			$newSize = $testParameters.newSize
			Set-HardDiskSize $vhdPath $newSize $controllerType $vmName $hvServer $ip $port
		}
		$testResult = "PASS"

	} catch {
		$testResult = "FAIL"
		$ErrorMessage =  $_.Exception.Message
		$ErrorLine = $_.InvocationInfo.ScriptLineNumber
		LogErr "$ErrorMessage at line: $ErrorLine"

	} finally {
		Stop-VM -VMName $vmName -ComputerName $hvServer -force
		Remove-VMHardDiskDrive -VMHardDiskDrive $vhdxDrive
		Remove-Item $vhdPath
		Start-VM -Name $vmName -ComputerName $hvServer
		$resultArr += $testResult
	}

	return GetFinalResultHeader -resultarr $resultArr
} # end Main

Main -vmName $VM.RoleName -hvServer $VM.HyperVHost -ip $VM.PublicIP -port $VM.SSHPort
