# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Synopsis
    Verify basic VHDx Hard Disk resizing.
.Description
    This is a PowerShell test case script that implements
	dynamic resizing of VHDX hard disk.
    Ensures that the VM detects the newly attached VHDx hard disk,
	creates partitions, filesytem, mounts partitions, detects if
	it can perform read/write operations on the newly created
	partitions and deletes partitions
.Parameter testParams
    Test data for this test case
#>

Param([String] $TestParams)

$ErrorActionPreference = "Stop"

Function Main
{
	param ($vmname, $hvserver, $ip, $port)

	$tps = Parse-TestParameters -XMLParams $CurrentTestData.TestParameters
	$resultArr = @()
	$testResult = $null

	try {
		# if host build number lower than 9600, skip test
		$BuildNumber = Get-HostBuildNumber $hvserver

		if ($BuildNumber -lt 9600) {
			$testResult = "ABORTED"
			Throw "Build number less than 9600"
		}

		if ($tps.Contains("IDE")) {
			$controllertype = "IDE"
		}
		elseif ($tps.Contains("SCSI")) {
			$controllertype = "SCSI"
		}
		else {
			$testResult = "ABORTED"
			Throw "Could not determine ControllerType"
		}

		if ( $controllertype -eq "IDE" ) {
			$vmGeneration = Get-VMGeneration $vmname $hvserver
			if ($vmGeneration -eq 2 ) {
				$testResult = "ABORTED"
				Throw "Generation 2 VM does not support IDE disk, skip test"
			}
		}

		$newVhdxSize = Convert-StringToUInt64 $tps.NewSize
		$sizeFlag = Convert-StringToUInt64 "20GB"

		# Make sure the VM has a SCSI 0 controller, and that
		# Lun 0 on the controller has a .vhdx file attached.

		LogMsg "Check if VM ${vmname} has a $controllertype drive"
		$vhdxName =  $vmname + "-" + $controllertype

		$vhdxDrive = Get-VMHardDiskDrive -VMName $vmname  -ComputerName $hvserver -ControllerLocation 1

		if (-not $vhdxDrive) {
			$testResult = "FAIL"
			Throw "No suitable virtual hard disk drives attached VM ${vmname}"
		}

		LogMsg "Check if the virtual disk file exists"
		$vhdPath = $vhdxDrive.Path
		$vhdxInfo = Get-RemoteFileInfo $vhdPath $hvserver
		if (-not $vhdxInfo) {
			$testResult = "FAIL"
			Throw "The vhdx file (${vhdPath} does not exist on server ${hvserver}"
		}

		LogMsg "Verify the file is a .vhdx"
		if (-not $vhdPath.EndsWith(".vhdx") -and -not $vhdPath.EndsWith(".avhdx")) {
			$testResult = "FAIL"
			Throw "$controllertype $vhdxDrive.ControllerNumber lun $vhdxDrive.ControllerLocation virtual disk is not a .vhdx file."
		}

		# Make sure there is sufficient disk space to grow the VHDX to the specified size
		$deviceID = $vhdxInfo.Drive
		$diskInfo = Get-CimInstance -Query "SELECT * FROM Win32_LogicalDisk Where DeviceID = '${deviceID}'" -ComputerName $hvserver
		if (-not $diskInfo) {
			$testResult = "FAIL"
			Throw "Unable to collect information on drive ${deviceID}"
		}

		# if disk is very large, e.g. 2T with dynamic, requires less disk free space
		if ($diskInfo.FreeSpace -le $sizeFlag + 10MB) {
			$testResult = "FAIL"
			Throw "Insufficent disk free space, This test case requires ${tps.NewSize} free, Current free space is $($diskInfo.FreeSpace)"
		}

		# Copy files from home of user to home of root
		$ret = RunLinuxCmd -ip $ip -port $port -username $user -password $password -command "cp -f /home/$user/STOR_VHDXResize_ReadWrite.sh /root/" -runAsSudo
		$ret = RunLinuxCmd -ip $ip -port $port -username $user -password $password -command "cp -f /home/$user/STOR_VHDXResize_PartitionDisk.sh /root/" -runAsSudo
		$ret = RunLinuxCmd -ip $ip -port $port -username $user -password $password -command "cp -f /home/$user/check_traces.sh /root/" -runAsSudo
		$ret = RunLinuxCmd -ip $ip -port $port -username $user -password $password -command "cp -f /home/$user/constants.sh /root/" -runAsSudo

		# Make sure if we can perform Read/Write operations on the guest VM
		$ret = RunLinuxCmd -ip $ip -port $port -username $user -password $password -command "./STOR_VHDXResize_PartitionDisk.sh" -runAsSudo
		if (-not $ret) {
			$testResult = "FAIL"
			Throw "Running '${guest_script}'script failed on VM. check VM logs , exiting test case execution"
		}

		# for IDE need to stop VM before resize
		if ( $controllertype -eq "IDE" ) {
			LogMsg "Resize IDE disc needs to turn off VM"
			Stop-VM -VMName $vmname -ComputerName $hvserver -force
		}

		Resize-VHD -Path $vhdPath -SizeBytes ($newVhdxSize) -ComputerName $hvserver

		if (-not $?) {
			$testResult = "FAIL"
			Throw "Unable to grow VHDX file ${vhdPath}"
		}

		LogMsg "Let system have some time for the volume change to be indicated. Sleep 5 ..."
		Start-Sleep -s 5

		# Now start the VM if IDE disk attached
		if ( $controllertype -eq "IDE" ) {
			$timeout = 300
			Start-VM -Name $vmname -ComputerName $hvserver
			if (-not (Wait-ForVMToStartKVP $vmname $hvserver $timeout )) {
				$testResult = "FAIL"
				Throw "${vmname} failed to start"
			} else {
				LogMsg "Started VM ${vmname}"
			}
		}

		# check file size after resize
		$vhdxInfoResize = Get-VHD -Path $vhdPath -ComputerName $hvserver

		if ( $tps.NewSize.contains("GB") -and $vhdxInfoResize.Size/1gb -ne $tps.NewSize.Trim("GB") ) {
			$testResult = "FAIL"
			Throw "Failed to Resize Disk to new Size"
		}

		LogMsg "Check if the guest detects the new space"

		$sd = "sdc"
		if ( $controllertype -eq "IDE" ) {
			$sd = "sdb"
		}
		# Older kernels might require a few requests to refresh the disks info
		$ret = RunLinuxCmd -ip $ip -port $port -username $user -password $password -command "fdisk -l > /dev/null" -runAsSudo
		$ret = RunLinuxCmd -ip $ip -port $port -username $user -password $password -command "echo 1 > /sys/block/$sd/device/rescan" -runAsSudo
		$diskSize = RunLinuxCmd -ip $ip -port $port -username $user -password $password -command "fdisk -l /dev/$sd  2> /dev/null | grep Disk | grep $sd | cut -f 5 -d ' '" -runAsSudo
		if (-not $diskSize) {
			$testResult = "FAIL"
			Throw "Unable to determine disk size from within the guest after growing the VHDX"
		}

		if ($diskSize -ne $newVhdxSize) {
			$testResult = "FAIL"
			Throw "VM ${vmname} detects a disk size of ${diskSize}, not the expected size of ${newVhdxSize}"
		}

		# Make sure if we can perform Read/Write operations on the guest VM
		if ([int]($newVhdxGrowSize/1gb) -gt 2048) {
			$ret = RunLinuxCmd -ip $ip -port $port -username $user -password $password -command "cp -f /home/$user/STOR_VHDXResize_PartitionDiskOver2TB.sh /root/" -runAsSudo
			$guest_script = "STOR_VHDXResize_PartitionDiskOver2TB.sh"
		} else {
			$guest_script = "STOR_VHDXResize_PartitionDisk.sh"
			$ret = RunLinuxCmd -ip $ip -port $port -username $user -password $password -command "echo 'rerun=yes' >> constants.sh" -runAsSudo
			$ret = RunLinuxCmd -ip $ip -port $port -username $user -password $password -command "cp -f /home/$user/constants.sh /root/" -runAsSudo
		}

		$ret = RunLinuxCmd -ip $ip -port $port -username $user -password $password -command "./$guest_script" -runAsSudo
		if (-not $ret) {
			$testResult = "FAIL"
			Throw "Running '${guest_script}'script failed on VM. check VM logs , exiting test case execution"
		}
		LogMsg "The guest detects the new size after resizing ($diskSize)"
		$testResult = "PASS"

	} catch {
		$ErrorMessage =  $_.Exception.Message
		$ErrorLine = $_.InvocationInfo.ScriptLineNumber
		LogErr "$ErrorMessage at line: $ErrorLine"

	} finally {
		Stop-VM -VMName $vmname -ComputerName $hvserver -force
		Remove-VMHardDiskDrive -VMHardDiskDrive $vhdxDrive
		Start-VM -Name $vmname -ComputerName $hvserver

		if (!$testResult) {
			$testResult = "ABORTED"
		}
		$resultArr += $testResult
	}

	$currentTestResult.TestResult = GetFinalResultHeader -resultarr $resultArr
	return $currentTestResult.TestResult
} # end Main

Main -vmname $allVMData.RoleName -hvserver $allVMData.HyperVHost -ip $AllVMData.PublicIP -port $AllVMData.SSHPort
