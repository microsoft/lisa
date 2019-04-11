##############################################################################################
# IntegrationServiceLibrary.psm1
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
# Operations :
#
<#
.SYNOPSIS
	PS modules for LISAv2 test automation.
	This module contains functions for testing Linux Integration Service

.PARAMETER
	<Parameters>

.INPUTS


.NOTES
	Creation Date:
	Purpose/Change:

.EXAMPLE


#>
###############################################################################################

Function Set-VMDynamicMemory
{
	param (
		$VM,
		$MinMem,
		$MaxMem,
		$StartupMem,
		$MemWeight
	)
	$MinMem = Convert-ToMemSize $MinMem $VM.HyperVHost
	$MaxMem = Convert-ToMemSize $MaxMem $VM.HyperVHost
	$StartupMem = Convert-ToMemSize $StartupMem $VM.HyperVHost
	Stop-VM -Name $VM.RoleName -ComputerName $VM.HyperVHost -force
	Set-VMMemory -vmName $VM.RoleName -ComputerName $VM.HyperVHost -DynamicMemoryEnabled $true `
		-MinimumBytes $MinMem -MaximumBytes $MaxMem -StartupBytes $StartupMem -Priority $MemWeight
	# check if mem is set correctly
	$vmMem = (Get-VMMemory -vmName $VM.RoleName -ComputerName $VM.HyperVHost).Startup
	if( $vmMem -eq $StartupMem ) {
		Write-LogInfo "Set VM Startup Memory for $($VM.RoleName) to $StartupMem"
		return $True
	}
	else {
		Write-LogErr "Unable to set VM Startup Memory for $($VM.RoleName) to $StartupMem"
		return $False
	}
}

Function Get-VMDemandMemory {
	param (
		[String] $VMName,
		[String] $Server,
		[int] $Timeout
	)
	$waitTimeOut = $Timeout
	while($waitTimeOut -gt 0) {
		$vm = Get-VM -Name $VMName -ComputerName $Server
		if (-not $vm) {
			Write-LogErr "Get-VMDemandMemory: Unable to find VM ${VMName}"
			return $false
		}
		if ($vm.MemoryDemand -and $vm.MemoryDemand -gt 0) {
			return $True
		}
		$waitTimeOut -= 5  # Note - Test Port will sleep for 5 seconds
		Start-Sleep -s 5
	}
	Write-LogErr "Get-VMDemandMemory: VM ${VMName} did not get demand within timeout period ($Timeout)"
	return $False
}

function Get-VMGeneration {
	# Get VM generation type from host, generation 1 or generation 2
	param (
		[String] $vmName,
		[String] $hvServer
	)

	# Hyper-V Server 2012 (no R2) only supports generation 1 VM
	$vmInfo = Get-VM -Name $vmName -ComputerName $hvServer
	if (!$vmInfo.Generation) {
		$vmGeneration = 1
	} else {
		$vmGeneration = $vmInfo.Generation
	}

	return $vmGeneration
}

Function Get-GuestInterfaceByVSwitch {
	param (
		[String] $VSwitchName,
		[String] $VMName,
		[String] $HvServer,
		[String] $GuestUser,
		[String] $GuestIP,
		[String] $GuestPassword,
		[String] $GuestPort
	)

	$testNic = $(Get-VM -Name $VMName -ComputerName $HvServer).NetworkAdapters `
				| Where-Object { $_.SwitchName -imatch $VSwitchName }
	$testMac = $testNic.MacAddress
	# The above $testMac doesn't have any separators - e.g. AABBCCDDEEFF
	for ($i=2; $i -lt 16; $i=$i+3) {
		$testMac = $testMac.Insert($i,':')
	}
	# We added ':' separators and now the MAC is in this format: AA:BB:CC:DD:EE:FF
	# Get the interface name that corresponds to the MAC address
	$cmdToSend = "testInterface=`$(grep -il ${testMac} /sys/class/net/*/address) ; basename `"`$(dirname `$testInterface)`""
	$testInterfaceName = Run-LinuxCmd -username $GuestUser -password $GuestPassword -ip $GuestIP -port $GuestPort `
		-command $cmdToSend -runAsSudo
	if (-not $testInterfaceName) {
		Write-LogErr "Failed to get the interface name that has $testMac MAC address"
		return $False
	}

	Write-LogInfo "The interface that will be configured on $VMName is $testInterfaceName"
	return $testInterfaceName
}

function Stop-FcopyDaemon{
	param(
		[String] $vmPassword,
		[String] $vmPort,
		[String] $vmUserName,
		[String] $ipv4
	)
	$sts = check_fcopy_daemon  -vmPassword $vmPassword -vmPort $vmPort -vmUserName $vmUserName -ipv4 $ipv4
	if ($sts[-1] -eq $True ){
		Write-Output "yes" | .\Tools\plink.exe -C -pw ${vmPassword} -P ${vmPort} ${vmUserName}@${ipv4} "pkill -f 'fcopy'"
		if (-not $?) {
			Write-LogErr "Unable to kill hypervfcopy daemon"
			return $False
		}
	}
	return $true
}

function Convert-KvpToDict($RawData) {
	<#
	.Synopsis
		Convert the KVP data to a PowerShell dictionary.

	.Description
		Convert the KVP xml data into a PowerShell dictionary.
		All keys are added to the dictionary, even if their
		values are null.

	.Parameter RawData
		The raw xml KVP data.

	.Example
		Convert-KvpToDict $myKvpData
	#>

	$dict = @{}

	foreach ($dataItem in $RawData) {
		$key = ""
		$value = ""
		$xmlData = [Xml] $dataItem

		foreach ($p in $xmlData.INSTANCE.PROPERTY) {
			if ($p.Name -eq "Name") {
				$key = $p.Value
			}
			if ($p.Name -eq "Data") {
				$value = $p.Value
			}
		}
		$dict[$key] = $value
	}

	return $dict
}

function Get-IPv4ViaKVP {
	# Try to determine a VMs IPv4 address with KVP Intrinsic data.
	param (
		[String] $VmName,
		[String] $HvServer
	)

	$vmObj = Get-WmiObject -Namespace root\virtualization\v2 -Query "Select * From Msvm_ComputerSystem Where ElementName=`'$VmName`'" -ComputerName $HvServer
	if (-not $vmObj) {
		Write-LogWarn "Get-IPv4ViaKVP: Unable to create Msvm_ComputerSystem object"
		return $null
	}

	$maxRetryTimes = 30
	$retryTime = 1
	while (($retryTime -lt $maxRetryTimes)) {
		$kvp = Get-WmiObject -Namespace root\virtualization\v2 -Query "Associators of {$vmObj} Where AssocClass=Msvm_SystemDevice ResultClass=Msvm_KvpExchangeComponent" -ComputerName $HvServer
		if (-not $kvp) {
			Write-LogWarn "Get-IPv4ViaKVP: Unable to create KVP exchange component"
			return $null
		}

		$rawData = $Kvp.GuestIntrinsicExchangeItems
		if (-not $rawData) {
			Write-LogWarn "Get-IPv4ViaKVP: No KVP Intrinsic data returned"
			return $null
		}

		$addresses = $null

		foreach ($dataItem in $rawData) {
			$found = 0
			$xmlData = [Xml] $dataItem
			foreach ($p in $xmlData.INSTANCE.PROPERTY) {
				if ($p.Name -eq "Name" -and $p.Value -eq "NetworkAddressIPv4") {
					$found += 1
				}

				if ($p.Name -eq "Data") {
					$addresses = $p.Value
					$found += 1
				}

				if ($found -eq 2) {
					$addrs = $addresses.Split(";")
					foreach ($addr in $addrs) {
						if ($addr.StartsWith("127.")) {
							Continue
						}
						if ($addr) {
							return $addr
						}
						$retryTime++
						Start-Sleep -Seconds 10
					}
				}
			}
		}
	}

	Write-LogWarn "Get-IPv4ViaKVP: No IPv4 address found for VM ${VmName}"
	return $null
}

function Get-IPv4AndWaitForSSHStart {
	# Wait for KVP start and
	# Get ipv4 via kvp
	# Wait for ssh start, test ssh.
	# Returns [String]ipv4 address if succeeded or $False if failed
	param (
		[String] $VmName,
		[String] $HvServer,
		[String] $VmPort,
		[String] $User,
		[String] $Password,
		[int] $StepTimeout
	)

	# Wait for KVP to start and able to get ipv4 address
	if (-not (Wait-ForVMToStartKVP $VmName $HvServer $StepTimeout)) {
		Write-LogErr "Get-IPv4AndWaitForSSHStart: Unable to get ipv4 from VM ${vmName} via KVP within timeout period ($StepTimeout)"
		return $False
	}

	# Get new ipv4 in case an new IP is allocated to vm after reboot
	$new_ip = Get-IPv4ViaKVP $vmName $hvServer
	if (-not ($new_ip)){
		Write-LogErr "Get-IPv4AndWaitForSSHStart: Unable to get ipv4 from VM ${vmName} via KVP"
		return $False
	}

	# Wait for port 22 open
	if (-not (Wait-ForVMToStartSSH $new_ip $stepTimeout)) {
		Write-LogErr "Get-IPv4AndWaitForSSHStart: Failed to connect $new_ip port 22 within timeout period ($StepTimeout)"
		return $False
	}

	# Cache fingerprint, Check ssh is functional after reboot
	Write-Output "yes" | .\Tools\plink.exe -C -pw $Password -P $VmPort $User@$new_ip 'exit 0'
	$TestConnection = .\Tools\plink.exe -C -pw $Password -P $VmPort $User@$new_ip "echo Connected"
	if ($TestConnection -ne "Connected") {
		Write-LogErr "Get-IPv4AndWaitForSSHStart: SSH is not working correctly after boot up"
		return $False
	}
	return $new_ip
}

function Wait-ForVMToStartKVP {
	# Wait for a Linux VM with the LIS installed to start the KVP daemon
	param (
		[String] $VmName,
		[String] $HvServer,
		[int] $StepTimeout
	)
	$ipv4 = $null
	$retVal = $False

	$waitTimeOut = $StepTimeout
	while ($waitTimeOut -gt 0) {
		$ipv4 = Get-IPv4ViaKVP $VmName $HvServer
		if ($ipv4) {
			return $True
		}

		$waitTimeOut -= 10
		Start-Sleep -s 10
	}

	Write-LogErr "Wait-ForVMToStartKVP: VM ${VmName} did not start KVP within timeout period ($StepTimeout)"
	return $retVal
}

function Wait-ForVMToStop {
	# Wait for a VM to enter the Hyper-V Off state.
	param (
		[String] $VmName,
		[String] $HvServer,
		[int] $Timeout
	)

	[System.Reflection.Assembly]::LoadWithPartialName("Microsoft.HyperV.PowerShell")
	$tmo = $Timeout
	while ($tmo -gt 0) {
		Start-Sleep -s 1
		$tmo -= 5

		$vm = Get-VM -Name $VmName -ComputerName $HvServer
		if (-not $vm) {
			return $False
		}

		if ($vm.State -eq [Microsoft.HyperV.PowerShell.VMState]::off) {
			return $True
		}
	}

	Write-LogErr "StopVM: VM did not stop within timeout period"
	return $False
}

function Get-ParentVHD {
	# To Get Parent VHD from VM
	param (
		[String] $vmName,
		[String] $hvServer
	)

	$ParentVHD = $null

	$VmInfo = Get-VM -Name $vmName -ComputerName $hvServer
	if (-not $VmInfo) {
	Write-LogErr "Unable to collect VM settings for ${vmName}"
	return $False
	}

	$vmGen = Get-VMGeneration $vmName $hvServer
	if ($vmGen -eq 1 ) {
		$Disks = $VmInfo.HardDrives
		foreach ($VHD in $Disks) {
			if (($VHD.ControllerLocation -eq 0) -and ($VHD.ControllerType -eq "IDE")) {
				$Path = Get-VHD $VHD.Path -ComputerName $hvServer
				if ([string]::IsNullOrEmpty($Path.ParentPath)) {
					$ParentVHD = $VHD.Path
				} else {
					$ParentVHD =  $Path.ParentPath
				}

				Write-LogInfo "Parent VHD Found: $ParentVHD "
			}
		}
	}
	if ( $vmGen -eq 2 ) {
		$Disks = $VmInfo.HardDrives
		foreach ($VHD in $Disks) {
			if (($VHD.ControllerLocation -eq 0 ) -and ($VHD.ControllerType -eq "SCSI")) {
				$Path = Get-VHD $VHD.Path -ComputerName $hvServer
				if ([string]::IsNullOrEmpty($Path.ParentPath)) {
					$ParentVHD = $VHD.Path
				} else {
					$ParentVHD =  $Path.ParentPath
				}
				Write-LogInfo "Parent VHD Found: $ParentVHD "
			}
		}
	}

	if (-not ($ParentVHD.EndsWith(".vhd") -xor $ParentVHD.EndsWith(".vhdx"))) {
		Write-LogErr "Parent VHD is Not correct please check VHD, Parent VHD is: $ParentVHD"
		return $False
	}

	return $ParentVHD
}

function Create-ChildVHD {
	param (
		[String] $ParentVHD,
		[String] $defaultpath,
		[String] $hvServer
	)

	$ChildVHD  = $null
	$hostInfo = Get-VMHost -ComputerName $hvServer
	if (-not $hostInfo) {
		Write-LogErr "Unable to collect Hyper-V settings for $hvServer"
		return $False
	}

	# Create Child VHD
	if ($ParentVHD.EndsWith("x")) {
		$ChildVHD = $defaultpath + ".vhdx"
	} else {
		$ChildVHD = $defaultpath + ".vhd"
	}

	if (Test-Path $ChildVHD) {
		Write-LogInfo "Remove-Itemeting existing VHD $ChildVHD"
		Remove-Item $ChildVHD
	}

	# Copy Child VHD
	Copy-Item "$ParentVHD" "$ChildVHD"
	if (-not $?) {
		Write-LogErr  "Unable to create child VHD"
		return $False
	}

	return $ChildVHD
}

function Convert-ToMemSize {
	param (
		[String] $memString,
		[String] $hvServer
	)
	$memSize = [Int64] 0

	if ($memString.EndsWith("MB")) {
		$num = $memString.Replace("MB","")
		$memSize = ([Convert]::ToInt64($num)) * 1MB
	} elseif ($memString.EndsWith("GB")) {
		$num = $memString.Replace("GB","")
		$memSize = ([Convert]::ToInt64($num)) * 1GB
	} elseif ($memString.EndsWith("%")) {
		$osInfo = Get-WmiObject Win32_OperatingSystem -ComputerName $hvServer
		if (-not $osInfo) {
			Write-LogErr "Unable to retrieve Win32_OperatingSystem object for server ${hvServer}"
			return $False
		}

		$hostMemCapacity = $osInfo.FreePhysicalMemory * 1KB
		$memPercent = [Convert]::ToDouble("0." + $memString.Replace("%",""))
		$num = [Int64] ($memPercent * $hostMemCapacity)

		# Align on a 4k boundary
		$memSize = [Int64](([Int64] ($num / 2MB)) * 2MB)
	} else {
		$memSize = ([Convert]::ToInt64($memString))
	}

	return $memSize
}

function Get-NumaSupportStatus {
	param (
		[string] $kernel
	)
	# Get whether NUMA is supported or not based on kernel version.
	# Generally, from RHEL 6.6 with kernel version 2.6.32-504,
	# NUMA is supported well.

	if ( $kernel.Contains("i686") -or $kernel.Contains("i386")) {
		return $false
	}

	if ($kernel.StartsWith("2.6")) {
		$numaSupport = "2.6.32.504"
		$kernelSupport = $numaSupport.split(".")
		$kernelCurrent = $kernel.replace("-",".").split(".")

		for ($i=0; $i -le 3; $i++) {
			if ($kernelCurrent[$i] -lt $kernelSupport[$i]) {
				return $false
			}
		}
	}

	# We skip the check if kernel is not 2.6
	# Anything newer will have support for it
	return $true
}

function Create-Controller{
	param (
		[string] $vmName,
		[string] $server,
		[string] $controllerID
	)

	#
	# Initially, we will limit this to 4 SCSI controllers...
	#
	if ($ControllerID -lt 0 -or $controllerID -gt 3)
	{
		Write-LogErr "Bad SCSI controller ID: $controllerID"
		return $False
	}

	#
	# Check if the controller already exists.
	#
	$scsiCtrl = Get-VMScsiController -VMName $vmName -ComputerName $server
	if ($scsiCtrl.Length -1 -ge $controllerID)
	{
	Write-LogInfo "SCSI controller already exists"
	}
	else
	{
		$error.Clear()
		Add-VMScsiController -VMName $vmName -ComputerName $server
		if ($error.Count -gt 0)
		{
		Write-LogErr "Add-VMScsiController failed to add 'SCSI Controller $ControllerID'"
			$error[0].Exception
			return $False
		}
		Write-LogInfo "Controller successfully added"
	}
	return $True
}

function Get-TimeSync {
	param (
		[String] $Ipv4,
		[String] $Port,
		[String] $Username,
		[String] $Password
	)

	# Get a time string from the VM, then convert the Unix time string into a .NET DateTime object
	$unixTimeStr = Run-LinuxCmd -ip $Ipv4 -port $Port -username $Username -password $Password `
		-command 'date "+%m/%d/%Y/%T" -u'
	if (-not $unixTimeStr) {
		Write-LogErr "Error: Unable to get date/time string from VM"
		return $False
	}

	$pattern = 'MM/dd/yyyy/HH:mm:ss'
	$unixTime = [DateTime]::ParseExact($unixTimeStr, $pattern, $null)

	# Get our time
	$windowsTime = [DateTime]::Now.ToUniversalTime()

	# Compute the timespan, then convert it to the absolute value of the total difference in seconds
	$diffInSeconds = $null
	$timeSpan = $windowsTime - $unixTime
	if (-not $timeSpan) {
		Write-LogErr "Error: Unable to compute timespan"
		return $False
	} else {
		$diffInSeconds = [Math]::Abs($timeSpan.TotalSeconds)
	}

	# Display the data
	Write-LogInfo "Windows time: $($windowsTime.ToString())"
	Write-LogInfo "Unix time: $($unixTime.ToString())"
	Write-LogInfo "Difference: $diffInSeconds"
	Write-LogInfo "Time difference = ${diffInSeconds}"
	return $diffInSeconds
}

function Optimize-TimeSync {
	param (
		[String] $Ipv4,
		[String] $Port,
		[String] $Username,
		[String] $Password
	)
	$testScript = "timesync_config.sh"
	$null = Run-LinuxCmd -ip $Ipv4 -port $Port -username $Username `
		-password $Password -command `
		"echo '${Password}' | sudo -S -s eval `"export HOME=``pwd``;bash ${testScript} > ${testScript}.log`""
	if (-not $?) {
		Write-LogInfo "Error: Failed to configure time sync. Check logs for details."
		return $False
	}
	return $True
}

function Check-FcopyDaemon{
	param (
		[string] $vmPassword,
		[string] $vmPort,
		[string] $vmUserName,
		[string] $ipv4
	)
<#
	.Synopsis
	Verifies that the fcopy_daemon
	.Description
	Verifies that the fcopy_daemon on VM and attempts to copy a file

	#>

	$filename = ".\fcopy_present"

	Run-LinuxCmd -username $vmUserName -password $vmPassword -port $vmPort -ip $ipv4  "ps -ef | grep '[h]v_fcopy_daemon\|[h]ypervfcopyd' > /tmp/fcopy_present" -runAsSudo
	if (-not $?) {
		Write-LogErr  "Unable to verify if the fcopy daemon is running"
		return $False
	}

	Copy-RemoteFiles -download -downloadFrom $Ipv4 -files "/tmp/fcopy_present" `
	-downloadTo $LogDir -port $vmPort -username $vmUserName -password $vmPassword
	if (-not $?) {
		Write-LogErr "Unable to copy the confirmation file from the VM"
		return $False
	}

	# When using grep on the process in file, it will return 1 line if the daemon is running
	if ((Get-Content -Path $LogDir\$filename  | Measure-Object -Line).Lines -eq  "1" ) {
		Write-LogInfo "hv_fcopy_daemon process is running."
		return $True
	}

	Remove-Item $filename
}

function Copy-FileVM{
	param(
		[string] $vmName,
		[string] $hvServer,
		[String] $filePath
	)
<#
	.Synopsis
	Copy the file to the Linux guest VM
	.Description
	Copy the file to the Linux guest VM

	#>

	$Error.Clear()
	Copy-VMFile -vmName $vmName -ComputerName $hvServer -SourcePath $filePath -DestinationPath "/mnt/test/" -FileSource host -ErrorAction SilentlyContinue
	if ($Error.Count -ne 0) {
		return $false
	}
	return $true
}

function Copy-CheckFileInLinuxGuest{
	param(
		[String] $vmName,
		[String] $hvServer,
		[String] $vmUserName,
		[String] $vmPassword,
		[String] $vmPort,
		[String] $ipv4,
		[String] $testfile,
		[Boolean] $overwrite,
		[Int] $contentlength,
		[String]$filePath,
		[String]$vhd_path_formatted
	)

	# Write the file
	$filecontent = Generate-RandomString -length $contentlength

	$filecontent | Out-File $testfile
	if (-not $?) {
		Write-LogErr "Cannot create file $testfile'."
		return $False
	}

	$filesize = (Get-Item $testfile).Length
	if (-not $filesize){
		Write-LogErr "Cannot get the size of file $testfile'."
		return $False
	}

	# Copy file to vhd folder
	Copy-Item -Path .\$testfile -Destination \\$hvServer\$vhd_path_formatted

	# Copy the file and check copied file
	$Error.Clear()
	if ($overwrite) {
		Copy-VMFile -vmName $vmName -ComputerName $hvServer -SourcePath $filePath -DestinationPath "/tmp/" -FileSource host -ErrorAction SilentlyContinue -Force
	}
	else {
		Copy-VMFile -vmName $vmName -ComputerName $hvServer -SourcePath $filePath -DestinationPath "/tmp/" -FileSource host -ErrorAction SilentlyContinue
	}
	if ($Error.Count -eq 0) {
		$sts = Check-FileInLinuxGuest -vmUserName $vmUserName -vmPassword $vmPassword -vmPort $vmPort -ipv4 $ipv4 -fileName "/tmp/$testfile" -checkSize $True -checkContent  $True
		if (-not $sts[-1]) {
			Write-LogErr "File is not present on the guest VM '${vmName}'!"
			return $False
		}
		elseif ($sts[0] -ne $filesize) {
			Write-LogErr "The copied file doesn't match the $filesize size."
			return $False
		}
		elseif ($sts[1] -ne $filecontent) {
			Write-LogErr "The copied file doesn't match the content '$filecontent'."
			return $False
		}
		else {
			Write-LogInfo "The copied file matches the $filesize size and content '$filecontent'."
		}
	}
	else {
		Write-LogErr "An error has occurred while copying the file to guest VM '${vmName}'."
		$error[0]
		return $False
	}
	return $True
}


Function Check-VSSDemon {
	param (
		[String] $VMName,
		[String] $HvServer,
		[String] $VMIpv4,
		[String] $VMPort
	)
	$remoteScript="STOR_VSS_Check_VSS_Daemon.sh"
	$retval = Invoke-RemoteScriptAndCheckStateFile $remoteScript $user $password $VMIpv4 $VMPort
	if ($retval -eq $False) {
		Write-LogErr "Running $remoteScript script failed on VM!"
		return $False
	}
	Write-LogInfo "VSS Daemon is running"
	return $True
}

Function New-BackupSetup {
	param (
		[String] $VMName,
		[String] $HvServer
	)
	Write-LogInfo "Removing old backups"
	try {
		Remove-WBBackupSet -MachineName $HvServer -Force -WarningAction SilentlyContinue
		if (-not $?) {
			Write-LogErr "Not able to remove existing BackupSet"
			return $False
		}
	}
	catch {
		Write-LogInfo "No existing backup's to remove"
	}
	# Check if the VM VHD in not on the same drive as the backup destination
	$vm = Get-VM -Name $VMName -ComputerName $HvServer
	# Get drive letter
	$sts = Get-DriveLetter $VMName $HvServer
	$driveletter = $global:driveletter
	if (-not $sts[-1]) {
		Write-LogErr "Cannot get the drive letter"
		return $False
	}
	foreach ($drive in $vm.HardDrives) {
		if ( $drive.Path.StartsWith("$driveletter")) {
			Write-LogErr "Backup partition $driveletter is same as partition hosting the VMs disk $($drive.Path)"
			return $False
		}
	}
	return $True
}

Function New-Backup {
	param (
		[String] $VMName,
		[String] $DriveLetter,
		[String] $HvServer,
		[String] $VMIpv4,
		[String] $VMPort
	)
	# Remove Existing Backup Policy
	try {
		Remove-WBPolicy -all -force
	}
	Catch {
		Write-LogInfo "No existing backup policy to remove"
	}
	# Set up a new Backup Policy
	$policy = New-WBPolicy
	# Set the backup location
	$backupLocation = New-WBBackupTarget -VolumePath $DriveLetter
	# Define VSS WBBackup type
	Set-WBVssBackupOption -Policy $policy -VssCopyBackup
	# Add the Virtual machines to the list
	$VM = Get-WBVirtualMachine | Where-Object VMName -like $VMName
	Add-WBVirtualMachine -Policy $policy -VirtualMachine $VM
	Add-WBBackupTarget -Policy $policy -Target $backupLocation
	# Start the backup
	Write-LogInfo "Backing to $DriveLetter"
	Start-WBBackup -Policy $policy
	# Review the results
	$BackupTime = (New-Timespan -Start (Get-WBJob -Previous 1).StartTime -End (Get-WBJob -Previous 1).EndTime).Minutes
	Write-LogInfo "Backup duration: $BackupTime minutes"
	$sts=Get-WBJob -Previous 1
	if ($sts.JobState -ne "Completed" -or $sts.HResult -ne 0) {
		Write-LogErr "VSS Backup failed"
		return $False
	}
	Write-LogInfo "Backup successful!"
	# Let's wait a few Seconds
	Start-Sleep -Seconds 5
	# Delete file on the VM
	$vmState = $(Get-VM -name $VMName -ComputerName $HvServer).state
	if (-not $vmState) {
		Run-LinuxCmd -username $user -password $password -ip $VMIpv4 -port $VMPort -command "rm /home/$user/1" -runAsSudo
		if (-not $?) {
			Write-LogErr "Cannot delete test file!"
			return $False
		}
		Write-LogInfo "File deleted on VM: $VMName"
	}
	return $backupLocation
}

Function Restore-Backup {
	param (
		$BackupLocation,
		$HypervGroupName,
		$VMName
	)
	# Start the Restore
	Write-LogInfo "Now let's restore the VM from backup."
	# Get BackupSet
	$BackupSet = Get-WBBackupSet -BackupTarget $BackupLocation
	# Start restore
	Start-WBHyperVRecovery -BackupSet $BackupSet -VMInBackup $BackupSet.Application[0].Component[0] -Force -WarningAction SilentlyContinue
	$sts=Get-WBJob -Previous 1
	if ($sts.JobState -ne "Completed" -or $sts.HResult -ne 0) {
		Write-LogErr "VSS Restore failed"
		return $False
	}
	# Add VM to VMGroup
	Add-VMGroupMember -Name $HypervGroupName -VM $(Get-VM -name $VMName)
	return $True
}

Function Check-VMStateAndFileStatus {
	param (
		[String] $VMName,
		[String] $HvServer,
		[String] $VMIpv4,
		[String] $VMPort
	)

	# Review the results
	$RestoreTime = (New-Timespan -Start (Get-WBJob -Previous 1).StartTime -End (Get-WBJob -Previous 1).EndTime).Minutes
	Write-LogInfo "Restore duration: $RestoreTime minutes"
	# Make sure VM exists after VSS backup/restore operation
	$vm = Get-VM -Name $VMName -ComputerName $HvServer
	if (-not $vm) {
		Write-LogErr "VM ${VMName} does not exist after restore"
		return $False
	}
	Write-LogInfo "Restore success!"
	$vmState = (Get-VM -name $VMName -ComputerName $HvServer).state
	Write-LogInfo "VM state is $vmState"
	$ip_address = Get-IPv4ViaKVP $VMName $HvServer
	$timeout = 300
	if ($vmState -eq "Running") {
		if ($null -eq $ip_address) {
			Write-LogInfo "Restarting VM ${VMName} to bring up network"
			Restart-VM -vmName $VMName -ComputerName $HvServer
			Wait-ForVMToStartKVP $VMName $HvServer $timeout
			$ip_address = Get-IPv4ViaKVP $VMName $HvServer
		}
	}
	elseif ($vmState -eq "Off" -or $vmState -eq "saved" ) {
		Write-LogInfo "Starting VM : ${VMName}"
		Start-VM -vmName $VMName -ComputerName $HvServer
		if (-not (Wait-ForVMToStartKVP $VMName $HvServer $timeout )) {
			Write-LogErr "${VMName} failed to start"
			return $False
		}
		else {
			$ip_address = Get-IPv4ViaKVP $VMName $HvServer
		}
	}
	elseif ($vmState -eq "Paused") {
		Write-LogInfo "Resuming VM : ${VMName}"
		Resume-VM -vmName $VMName -ComputerName $HvServer
		if (-not (Wait-ForVMToStartKVP $VMName $HvServer $timeout )) {
			Write-LogErr "${VMName} failed to resume"
			return $False
		}
		else {
			$ip_address = Get-IPv4ViaKVP $VMName $HvServer
		}
	}
	Write-LogInfo "${VMName} IP is $ip_address"
	# check selinux denied log after IP injection
	$sts=Get-SelinuxAVCLog -ipv4 $VMIpv4 -SSHPort $VMPort -Username "root" -Password $password
	if (-not $sts) {
		return $False
	}
	# only check restore file when IP available
	$stsipv4 = Test-NetConnection $VMIpv4 -Port 22 -WarningAction SilentlyContinue
	if ($stsipv4.TcpTestSucceeded) {
		$sts = Run-LinuxCmd -username $user -password $password -ip $VMIpv4 -port $VMPort -command "stat /home/$user/1"
		if (-not $sts) {
			Write-LogErr "No /home/$user/1 file after restore"
			return $False
		}
		else {
			Write-LogInfo "there is /home/$user/1 file after restore"
		}
	}
	else {
		Write-LogInfo "Ignore checking file /home/$user/1 when no network"
	}
	return $True
}

Function Remove-Backup {
	param (
		[String] $BackupLocation
	)
	# Remove Created Backup
	Write-LogInfo "Removing old backups from $BackupLocation"
	try {
		Remove-WBBackupSet -BackupTarget $BackupLocation -Force -WarningAction SilentlyContinue
	}
	Catch {
		Write-LogInfo "No existing backups to remove"
	}
}

Function Get-BackupType() {
	# check the latest successful job backup type, "online" or "offline"
	$backupType = $null
	$sts = Get-WBJob -Previous 1
	if ($sts.JobState -ne "Completed" -or $sts.HResult -ne 0) {
		Write-LogErr "Error: VSS Backup failed "
		return $backupType
	}
	$contents = Get-Content $sts.SuccessLogPath
	foreach ($line in $contents ) {
		if ( $line -match "Caption" -and $line -match "online") {
			Write-LogInfo "VSS Backup type is online"
			$backupType = "online"
		}
		elseif ($line -match "Caption" -and $line -match "offline") {
			Write-LogInfo "VSS Backup type is offline"
			$backupType = "offline"
		}
	}
	return $backupType
}

Function Get-DriveLetter {
	param (
		[string] $VMName,
		[string] $HvServer
	)
	if ($null -eq $VMName) {
		Write-LogErr "VM ${VMName} name was not specified."
		return $False
	}
	# Get the letter of the mounted backup drive
	$tempFile = (Get-VMHost -ComputerName $HvServer).VirtualHardDiskPath + "\" + $VMName + "_DRIVE_LETTER.txt"
	if(Test-Path ($tempFile)) {
		$global:driveletter = Get-Content -Path $tempFile
		# To avoid PSUseDeclaredVarsMoreThanAssignments warning when run PS Analyzer
		Write-LogInfo "global parameter driveletter is set to $global:driveletter"
		return $True
	}
	else {
		return $False
	}
}

function Get-KVPItem {
	param (
		$VMName,
		$server,
		$keyName,
		$Intrinsic
	)

	$vm = Get-WmiObject -ComputerName $server -Namespace root\virtualization\v2 -Query "Select * From Msvm_ComputerSystem Where ElementName=`'$VMName`'"
	if (-not $vm)
	{
		return $Null
	}

	$kvpEc = Get-WmiObject -ComputerName $server  -Namespace root\virtualization\v2 -Query "Associators of {$vm} Where AssocClass=Msvm_SystemDevice ResultClass=Msvm_KvpExchangeComponent"
	if (-not $kvpEc)
	{
		return $Null
	}

	$kvpData = $Null

	if ($Intrinsic)
	{
		$kvpData = $KvpEc.GuestIntrinsicExchangeItems
	}else{
		$kvpData = $KvpEc.GuestExchangeItems
	}

	if ($kvpData -eq $Null)
	{
		return $Null
	}

	foreach ($dataItem in $kvpData)
	{
		$key = $null
		$value = $null
		$xmlData = [Xml] $dataItem

		foreach ($p in $xmlData.INSTANCE.PROPERTY)
		{
			if ($p.Name -eq "Name")
			{
				$key = $p.Value
			}

			if ($p.Name -eq "Data")
			{
				$value = $p.Value
			}
		}
		if ($key -eq $keyName)
		{
			return $value
		}
	}

	return $Null
}

# Set the Integration Service status based on service name and expected service status.
function Set-IntegrationService {
	param (
		[string] $VMName,
		[string] $HvServer,
		[string] $ServiceName,
		[boolean] $ServiceStatus
	)
	if (@("Guest Service Interface", "Time Synchronization", "Heartbeat", "Key-Value Pair Exchange", "Shutdown","VSS") -notcontains $ServiceName) {
		Write-LogErr "Unknown service type: $ServiceName"
		return $false
	}
	if ($ServiceStatus -eq $false) {
		Disable-VMIntegrationService -ComputerName $HvServer -VMName $VMName -Name $ServiceName
	}
	else {
		Enable-VMIntegrationService -ComputerName $HvServer -VMName $VMName -Name $ServiceName
	}
	$status = Get-VMIntegrationService -ComputerName $HvServer -VMName $VMName -Name $ServiceName
	if ($status.Enabled -ne $ServiceStatus) {
		Write-LogErr "The $ServiceName service could not be set as $ServiceStatus"
		return $False
	}
	return $True
}