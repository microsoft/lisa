# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
param([object] $AllVmData, [object] $CurrentTestData)

function New-RaidOnL1 ($session, $interleave) {
	Write-LogInfo "Create raid0 on level 1 with $interleave Interleave"
	Invoke-Command -Session $session -ScriptBlock {
		param($interleave)

		$poolName = "Raid0-Pool"
		$raidDiskName = "Raid0-Disk"

		$diskNumbers = (Get-Disk | Where-Object {$_.FriendlyName -eq 'Msft Virtual Disk'}).Number
		foreach ( $number in $diskNumbers ) {
			Set-Disk $number -isOffline $true
		}

		$disks = Get-PhysicalDisk -CanPool  $true
		New-StoragePool -StorageSubSystemFriendlyName "Windows Storage*"  -FriendlyName $poolName -PhysicalDisks $disks
		New-VirtualDisk -FriendlyName $raidDiskName -StoragePoolFriendlyName $poolName  -Interleave $interleave -UseMaximumSize -ResiliencySettingName Simple
		$diskNumber = ( get-disk | Where-Object{ $_.FriendlyName -eq $raidDiskName } ).Number
		Set-Disk  $diskNumber -IsOffline $true
	} -ArgumentList $interleave
}

function New-NestedVM ($session, $vmMem, $osVHD, $vmName, $processors, $switchName) {
	Write-LogInfo "Create the $vmName VM with mem:$vmMem, processors:$processors"
	Invoke-Command -Session $session -ScriptBlock {
			param($vmMem,$osVHD,$vmName,$processors,$switchName)

			$savePath = "C:\Users\"
			$currentVMOsVHDPath = $savePath + $vmName + ".vhd"

			New-VHD -ParentPath $osVHD -Path $currentVMOsVHDPath

			$NewVM = New-VM -Name $vmName -MemoryStartupBytes $vmMem -BootDevice VHD -VHDPath $currentVMOsVHDPath -Path $savePath -Generation 1 -Switch $switchName
			if ($?) {
				Set-VM -VM $NewVM -ProcessorCount $processors -StaticMemory -CheckpointType Disabled

				$diskNumbers = (Get-Disk | Where-Object {$_.FriendlyName -eq 'Msft Virtual Disk'}).Number
				foreach ( $number in $diskNumbers ) {
					Set-Disk $number -isOffline $true
				}

				$diskNumbers = (Get-Disk | Where-Object {$_.OperationalStatus -eq 'offline'}).Number
				$count = 0
				foreach ( $lun in $diskNumbers ) {
					"Add physical disk $($diskNumbers[$count]) to controller on virtual machine $vmName."
					$NewVM | Add-VMHardDiskDrive -DiskNumber $($diskNumbers[$count]) -ControllerType 'SCSI'
					$count ++
				}
			}

		} -ArgumentList $vmMem, $osVHD, $vmName, $processors, $switchName
}

function Get-NestedVMIPAdress ($session, $vmName) {
	#Start the nested vm if it's not running
	Write-LogInfo "Get the IPv4 address of the nested VM $vmName"
	Invoke-Command -Session $session -ScriptBlock {
		param($vmName)

		$status = Get-VM -Name $vmName
		if ($($status.State) -ne "running") {
			Start-VM -Name $vmName
			Start-Sleep 10
		}
	} -ArgumentList $vmName

	$MaxCount = 20
	$i=0
	do {
		$i++
		Start-Sleep 30
		$VMNicProperties = Invoke-Command -Session $session -ScriptBlock {
			param($vmName)

			Get-VMNetworkAdapter -VMName $vmName
		}  -ArgumentList $vmName

		$nestedVmIP = $VMNicProperties.IPAddresses | Where-Object {$_ -imatch "\b(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(\.(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}\b"}
	} while (($i -lt $MaxCount) -and (!$nestedVmIP))

	return $nestedVmIP
}

function New-ShellScriptFile($username) {
	$scriptContent = @"
echo nameserver 8.8.8.8 >> /etc/resolv.conf
chmod +x nested_kvm_perf_fio.sh
./nested_kvm_perf_fio.sh &> fioConsoleLogs.txt
. utils.sh
collect_VM_properties nested_properties.csv
"@

	$scriptContent2 = @"
chmod +x *.sh
cp fio_jason_parser.sh gawk JSON.awk utils.sh /home/$username/FIOLog/jsonLog/
cd /home/$username/FIOLog/jsonLog/
bash fio_jason_parser.sh
cp perf_fio.csv /home/$username/
cd /home/$username/
chmod 666 perf_fio.csv

"@
	Set-Content "$LogDir\StartFioTest.sh" $scriptContent
	Set-Content "$LogDir\ParseFioTestLogs.sh" $scriptContent2
}

function Start-TestExecution ($ip, $port, $username, $passwd) {
	Copy-RemoteFiles -uploadTo $ip -port $port -files $currentTestData.files -username $username -password $passwd -upload
	Run-LinuxCmd -ip $ip -port $port -username $username -password $passwd -command "rm -f /home/$username/*.txt;rm -f /home/$username/*.log" -runAsSudo
	Run-LinuxCmd -ip $ip -port $port -username $username -password $passwd -command "cp *.sh /root;touch /home/$username/state.txt" -runAsSudo
	Run-LinuxCmd -ip $ip -port $port -username $username -password $passwd -command "chmod +x *.sh;chmod +x /root/*.sh" -runAsSudo
	Write-LogInfo "Executing : StartFioTest.sh"
	$cmd = "/home/$username/StartFioTest.sh"
	Run-LinuxCmd -ip $ip -port  $port -username $username -password $passwd -command $cmd -runAsSudo  -runMaxAllowedTime  24000  -RunInBackground
	$currentStatus = Run-LinuxCmd -ip $ip -port  $port -username $username -password $passwd -command "cat /home/$username/state.txt"  -runAsSudo
	while ( $currentStatus -like "*TestRunning*" -or -not $currentStatus ) {
		$currentStatus = Run-LinuxCmd -ip $ip -port  $port -username $username -password $passwd -command "cat /home/$username/state.txt"  -runAsSudo
		Write-LogInfo "Current test status : $currentStatus"
		Wait-Time -seconds 30
	}

	Write-LogInfo "Executing : ParseFioTestLogs.sh"
	$cmd = "/home/$username/ParseFioTestLogs.sh > /home/$username/TestExecutionConsole.log"
	Run-LinuxCmd -ip $ip -port  $port -username $username -password $passwd -command $cmd -runAsSudo
}

function Get-SQLQueryOfNestedHyperv ($currentTestResult, $session, $AllVMData) {
	try {
		$TestDate = $(Get-Date -Format yyyy-MM-dd)
		$fioDataCsv = Import-Csv -Path $LogDir\fioData.csv

		if ($TestPlatform -eq "hyperV") {
			$HyperVMappedSizes = [xml](Get-Content .\XML\AzureVMSizeToHyperVMapping.xml)
			$L1GuestCpuNum = $HyperVMappedSizes.HyperV.$HyperVInstanceSize.NumberOfCores
			$L1GuestMemMB = [int]($HyperVMappedSizes.HyperV.$HyperVInstanceSize.MemoryInMB)
			$L1GuestSize = "$($L1GuestCpuNum)Cores $($L1GuestMemMB/1024)G"
			$HostOS = (Get-WmiObject -Class Win32_OperatingSystem -ComputerName $GlobalConfig.Global.$TestPlatform.Hosts.ChildNodes[0].ServerName).Version
			$vm = Get-VM -Name $AllVMData.RoleName -ComputerName $AllVMData.HyperVHost
			$vhd = Get-VHD -Path $vm.HardDrives[1].Path
			$count = $vm.HardDrives.count - 1
			$disk_size = $vhd.PhysicalSectorSize
		} else {
			$L1GuestSize = $AllVMData.InstanceSize
			$keys = "HostingSystemOsMajor", "HostingSystemOsMinor", "HostingSystemEditionId"
			$registryEntry =  'HKLM:\SOFTWARE\Microsoft\Virtual Machine\Guest\Parameters'
			$values = @()
			foreach ( $key in $keys ) {
				$val = Invoke-Command -Session $session -ScriptBlock {
					param($registryEntry, $key)
					(get-item $registryEntry).GetValue("$key")
				} -ArgumentList $registryEntry, $key
				$values += $val
			}
			$HostOS = [string]$values[0]+ "." + [string]$values[1] + "." + [string]$values[2]
			$vm = (Get-AzureRmVM -ResourceGroupName $AllVMData.ResourceGroupName -Name $AllVMData.RoleName)
			$count = $vm.StorageProfile.DataDisks.Count
			$disk_size = $vm.StorageProfile.DataDisks[0].DiskSizeGB
		}
		$computerInfo = Invoke-Command -Session $session -ScriptBlock {Get-ComputerInfo}

		foreach ( $param in $currentTestData.TestParameters.param ) {
			if ($param -match "NestedCpuNum") {
				$L2GuestCpuNum = [int]($param.split("=")[1])
			}
			if ($param -match "NestedMemMB") {
				$L2GuestMemMB = [int]($param.split("=")[1])
			}
			if ($param -match "startThread") {
				$startThread = [int]($param.split("=")[1])
			}
			if ($param -match "maxThread") {
				$maxThread = [int]($param.split("=")[1])
			}
			if ($param -match "RaidOption") {
				$RaidOption = $param.Replace("RaidOption=","").Replace("'","")
			}
		}

		for ( $QDepth = $startThread; $QDepth -le $maxThread; $QDepth *= 2 ) {
			$resultMap = @{}
			$resultMap["TestCaseName"] = $GlobalConfig.Global.$TestPlatform.ResultsDatabase.testTag
			$resultMap["TestDate"] = $TestDate
			$resultMap["HostType"] = $TestPlatform
			$resultMap["HostBy"] = $TestLocation
			$resultMap["HostOS"] = $HostOS
			$resultMap["L1GuestOSType"] = "Windows"
			$resultMap["L1GuestDistro"] = $computerInfo.OsName
			$resultMap["L1GuestSize"] = $L1GuestSize
			$resultMap["L1GuestKernelVersion"] = $(Get-Content "$LogDir\nested_properties.csv" | Select-String "Host Version"| ForEach-Object {$_ -replace ",Host Version,",""})
			$resultMap["L2GuestDistro"] = $(Get-Content "$LogDir\nested_properties.csv" | Select-String "OS type"| ForEach-Object {$_ -replace ",OS type,",""})
			$resultMap["L2GuestKernelVersion"] = $(Get-Content "$LogDir\nested_properties.csv" | Select-String "Kernel version"| ForEach-Object {$_ -replace ",Kernel version,",""})
			$resultMap["L2GuestCpuNum"] = $L2GuestCpuNum
			$resultMap["L2GuestMemMB"] = $L2GuestMemMB
			$resultMap["DiskSetup"] = "$count SSD: $($disk_size)G"
			$resultMap["RaidOption"] = $RaidOption
			$resultMap["BlockSize_KB"] = [Int] ((($fioDataCsv |  Where-Object { $_.Threads -eq "$QDepth"} | Select-Object BlockSize)[0].BlockSize).Replace("K",""))
			$resultMap["QDepth"] = $QDepth
			$resultMap["seq_read_iops"] = [Float] (($fioDataCsv |  Where-Object { $_.TestType -eq "read" -and  $_.Threads -eq "$QDepth"} | Select-Object ReadIOPS).ReadIOPS)
			$resultMap["seq_read_lat_usec"] = [Float] (($fioDataCsv |  Where-Object { $_.TestType -eq "read" -and  $_.Threads -eq "$QDepth"} | Select-Object MaxOfReadMeanLatency).MaxOfReadMeanLatency)
			$resultMap["rand_read_iops"] = [Float] (($fioDataCsv |  Where-Object { $_.TestType -eq "randread" -and  $_.Threads -eq "$QDepth"} | Select-Object ReadIOPS).ReadIOPS)
			$resultMap["rand_read_lat_usec"] = [Float] (($fioDataCsv |  Where-Object { $_.TestType -eq "randread" -and  $_.Threads -eq "$QDepth"} | Select-Object MaxOfReadMeanLatency).MaxOfReadMeanLatency)
			$resultMap["seq_write_iops"] = [Float] (($fioDataCsv |  Where-Object { $_.TestType -eq "write" -and  $_.Threads -eq "$QDepth"} | Select-Object WriteIOPS).WriteIOPS)
			$resultMap["seq_write_lat_usec"] = [Float] (($fioDataCsv |  Where-Object { $_.TestType -eq "write" -and  $_.Threads -eq "$QDepth"} | Select-Object MaxOfWriteMeanLatency).MaxOfWriteMeanLatency)
			$resultMap["rand_write_iops"] = [Float] (($fioDataCsv |  Where-Object { $_.TestType -eq "randwrite" -and  $_.Threads -eq "$QDepth"} | Select-Object WriteIOPS).WriteIOPS)
			$resultMap["rand_write_lat_usec"] = [Float] (($fioDataCsv |  Where-Object { $_.TestType -eq "randwrite" -and  $_.Threads -eq "$QDepth"} | Select-Object MaxOfWriteMeanLatency).MaxOfWriteMeanLatency)
			$currentTestResult.TestResultData += $resultMap
		}
	} catch {
		Write-LogErr "Getting the SQL query of test results:  ERROR"
		$errorMessage =  $_.Exception.Message
		$ErrorLine = $_.InvocationInfo.ScriptLineNumber
		Write-LogInfo "EXCEPTION : $errorMessage at line: $ErrorLine"
	}
}

function New-CustomScript() {
	Write-LogInfo "Create the content of custom script"
	$customScriptName = "myCustomScript.ps1"
	$customScriptContent = @"
netsh advfirewall firewall add rule name="WinRM HTTP" dir=in action=allow protocol=TCP localport=5985 profile=public
"@

	Set-Content  "$LogDir\$customScriptName"  $customScriptContent

	$rgName = $AllVMData.ResourceGroupName
	$containerName = "vhds"
	$storageName = (Get-AzureRmStorageAccount -ResourceGroupName $rgName).StorageAccountName
	if (-not $storageName) {
		$randomNum = Get-Random -Maximum 999 -Minimum 100
		$storageName = "temp" + [string]$randomNum
		$location = $global:TestLocation
		New-AzureRmStorageAccount -ResourceGroupName $rgName -AccountName $storageName -Location $location -SkuName "Standard_GRS"   | Out-Null
	}
	$StorageKey = (Get-AzurermStorageAccountKey  -Name $storageName -ResourceGroupName $rgName).Value[0]
	$sourceContext = New-AzureStorageContext -StorageAccountName $storageName -StorageAccountKey $StorageKey
	$blobContainer = Get-AzureStorageContainer -Name $containerName -Context $sourceContext 2>$null
	if ($null -eq $blobContainer) {
		Write-LogInfo "The container $containerName doesn't exist, so create it."
		New-AzureStorageContainer -Name $containerName -Context $sourceContext   | Out-Null
		Start-Sleep 3
		$blobContainer = Get-AzureStorageContainer -Name $containerName -Context $sourceContext
	}

	Write-LogInfo "Upload the custom script to $blobContainer"
	Set-AzureStorageBlobContent -File "$LogDir\$customScriptName" -Container $containerName  -Context $sourceContext   | Out-Null

	$customScriptURI = $blobContainer.CloudBlobContainer.Uri.ToString() + "/" + $customScriptName
	return $customScriptURI
}

function Invoke-CustomScript($fileUri) {
	Write-LogInfo "Run custom script: $fileUri"
	$myVM = $AllVMData.RoleName
	$rgName = $AllVMData.ResourceGroupName
	$cutomeFile = $fileUri.Split("/")[-1]
	$stNameSavedScript = $fileUri.split("//")[2].split(".")[0]
	$customeFileUri = @("$fileUri")
	$settings = @{"fileUris" = $customeFileUri};

	$rgNameSavedScript = Get-AzureRmStorageAccount | Where-Object {$_.StorageAccountName -eq $stNameSavedScript} | Select-Object -ExpandProperty ResourceGroupName
	$stKeySavedScript = (Get-AzurermStorageAccountKey  -Name $stNameSavedScript -ResourceGroupName $rgNameSavedScript).Value[0]
	$proSettings = @{"storageAccountName" = $stNameSavedScript; "storageAccountKey" = $stKeySavedScript; "commandToExecute" = "powershell -ExecutionPolicy Unrestricted -File $cutomeFile"};
	$publisher = "Microsoft.Compute"
	$type = "CustomScriptExtension"
	$name = "CustomScriptExtension"
	$location = $global:TestLocation
	$sts=Set-AzureRmVMExtension -ResourceGroupName $rgName -Location $location -VMName $myVM  -Name $name -Publisher $publisher -ExtensionType $type  -TypeHandlerVersion "1.9"  -Settings $settings  -ProtectedSettings $proSettings
	if ($sts.IsSuccessStatusCode) {
	  Write-LogInfo "Run custom script successfully."
	} else {
	  Write-LogErr "Run custom script failed."
	}
}

function Get-OSvhd ($session, $srcPath, $dstPath) {
	Write-LogInfo "Downloading vhd from $srcPath to $dstPath ..."
	if ($srcPath.Trim().StartsWith("http")) {
		Invoke-Command -Session $session -ScriptBlock {
			param($srcPath, $dstPath)
			Import-Module BitsTransfer
			$displayName = "MyBitsTransfer" + (Get-Date)
			Start-BitsTransfer `
				-Source $srcPath `
				-Destination $dstPath `
				-DisplayName $displayName `
				-Asynchronous
			$btjob = Get-BitsTransfer $displayName
			$lastStatus = $btjob.JobState
			do {
				if ($lastStatus -ne $btjob.JobState) {
					$lastStatus = $btjob.JobState
				}

				if ($lastStatus -like "*Error*") {
					Remove-BitsTransfer $btjob
					Write-Output "Error connecting $srcPath to download."
					return 1
				}
			} while ($lastStatus -ne "Transferring")

			do {
				Write-Output (Get-Date) $btjob.BytesTransferred $btjob.BytesTotal ($btjob.BytesTransferred/$btjob.BytesTotal*100)
				Start-Sleep -s 10
			} while ($btjob.BytesTransferred -lt $btjob.BytesTotal)

			Write-Output (Get-Date) $btjob.BytesTransferred $btjob.BytesTotal ($btjob.BytesTransferred/$btjob.BytesTotal*100)
			Complete-BitsTransfer $btjob
		}  -ArgumentList $srcPath, $dstPath
	} else {
		Copy-Item $srcPath -Destination $dstPath -ToSession $session
	}
}

function Install-Hyperv ($session) {
	Write-LogInfo "Install Hyper-V and restart the host"
	Invoke-Command -Session $session -ScriptBlock { Install-WindowsFeature -Name Hyper-V -IncludeManagementTools -Restart }
	Start-Sleep 100
}

function New-NetworkSwitch ($session, $switchName) {
	Write-LogInfo "Start to create a network switch named $switchName"
	Invoke-Command -Session $session -ScriptBlock {
		param($switchName)
		$switchNames = (Get-VMSwitch).name
		foreach ( $vmswitchName in $switchNames ) {
			Remove-VMSwitch $vmswitchName -Force
		}

		$netAdapterNames  = (Get-NetAdapter).name
		foreach ( $netAdapterName in $netAdapterNames ) {
			if ($netAdapterName -like "*vEthernet*") {
				continue
			} else {
				New-VMSwitch -name $switchName -NetAdapterName $netAdapterName -AllowManagementOS $true
				break
			}
		}

	}  -ArgumentList $switchName
}

function New-NAT ($session, $switchName, $natName) {
	Write-LogInfo "Start to create a network NAT named $natName"
	Invoke-Command -Session $session -ScriptBlock {
		param($switchName, $natName)
		New-VMSwitch -Name $switchName -SwitchType Internal
		$interfaceIndex =  (Get-NetAdapter -Name "*$switchName*").ifindex
		New-NetIPAddress -IPAddress "192.168.0.1" -PrefixLength 24 -InterfaceIndex $interfaceIndex
		New-NetNat -Name $natName -InternalIPInterfaceAddressPrefix "192.168.0.0/24"
	} -ArgumentList $switchName, $natName

	Write-LogInfo "Create the network NAT named $natName completes."
}

function Add-NestedNatStaticMapping ($session, $natName, $ip_addr, $internalPort, $externalPort) {
	Write-LogInfo "Mapping $ip_addr internal port $internalPort external port $externalPort "
	Invoke-Command -Session $session -ScriptBlock {
		param($natName, $ip_addr, $internalPort, $externalPort)
		Add-NetNatStaticMapping -NatName $natName -Protocol TCP -ExternalIPAddress "0.0.0.0" -InternalIPAddress $ip_addr -InternalPort $internalPort -ExternalPort $externalPort
	} -ArgumentList $natName, $ip_addr, $internalPort, $externalPort
}

function Main() {
	$currentTestResult = Create-TestResultObject
	$resultArr = @()
	$testResult = $resultAborted
	try {
		$hs1VIP = $AllVMData.PublicIP

		# Get the test parameters
		foreach ( $param in $currentTestData.TestParameters.param ) {

			if ($param -imatch "RaidOption") {
				$RaidOption = $param.Replace("RaidOption=","").Replace("'","")
			}
			if ($param -imatch "NestedCpuNum=") {
					$nestedCPUs = [int]$param.Replace("NestedCpuNum=","")
			}
			if ($param -imatch "NestedMemMB=") {
					$nestedMemMB = [int]$param.Replace("NestedMemMB=","")
			}
			if ($param -imatch "NestedUser=") {
					$nestedVmUser = $param.Replace("NestedUser=","").Replace("'","")
			}
			if ($param -imatch "NestedUserPassword=") {
				$nestedVmPassword = $param.Replace("NestedUserPassword=","").Replace("'","")
			}
			if ($param -imatch "NestedImageUrl=") {
				$nestedVhdPath = $param.Replace("NestedImageUrl=","").Replace("'","").Trim()
			}
			if ($param -imatch "Interleave=") {
				$interleave = [int]$param.Replace("Interleave=","")
			}
		}

		if ($testPlatform -eq "Azure") {
			$customScriptUri = New-CustomScript
			Invoke-CustomScript -fileUri $customScriptUri | Out-Null
		}

		# Create remote session
		$cred = Get-Cred -user $user -password $password
		if ($testPlatform -eq "Azure") {
			$sessionPort = 5985
			$connectionURL = "http://${hs1VIP}:${sessionPort}"
			Write-LogInfo "Session connection URL: $connectionURL"
			$session = New-PSSession -ConnectionUri $connectionURL -Credential $cred -SessionOption (New-PSSessionOption -SkipCACheck -SkipCNCheck -SkipRevocationCheck)
		} else {
			$session = New-PSSession -ComputerName $hs1VIP -Credential $cred
		}

		if ($RaidOption -eq "RAID in L1") {
			New-RaidOnL1  -session $session -interleave $interleave | Out-Null
		}

		# Download L2 OS vhd
		$curtime = ([string]((Get-Date).Ticks / 1000000)).Split(".")[0]
		$nestOSVHD = "C:\Users\test_" + "$curtime" +".vhd"
		Get-OSvhd -session $session -srcPath $nestedVhdPath -dstPath $nestOSVHD | Out-Null

		if ($testPlatform -eq "Azure") {
			try {
				Install-Hyperv -Session $session | Out-Null
			} catch {
				# Ignore the exception caused by Hyper-V is installation
				$()
			}

			#Installation of Hyper-v will restart the vm, so renew the session
			$session = New-PSSession -ConnectionUri $connectionURL -Credential $cred -SessionOption (New-PSSessionOption -SkipCACheck -SkipCNCheck -SkipRevocationCheck)
		}

		$nestedVMMemory = $nestedMemMB * 1024 * 1024
		$nestedVMName = "LinuxNestedVM"
		$nestedVMSwithName = "MySwitch"
		$nestedNATName = "MyNATNet"

		if ($testPlatform -eq "Azure") {
			New-NAT -session $session -switchName $nestedVMSwithName -natName $nestedNATName | Out-Null
		} else {
			New-NetworkSwitch -session $session -switchName $nestedVMSwithName | Out-Null
		}

		New-NestedVM -session $session -vmMem  $nestedVMMemory  -osVHD $nestOSVHD -vmName $nestedVMName -processors $nestedCPUs -switchName $nestedVMSwithName | Out-Null

		$nestedVmIP = Get-NestedVMIPAdress -session $session  -vmName $nestedVMName

		if ($testPlatform -eq "Azure") {
			$nestedVmSSHPort = 222
			Add-NestedNatStaticMapping  -session $session  -natName $nestedNATName -ip_addr $nestedVmIP  -internalPort 22 -externalPort $nestedVmSSHPort | Out-Null
			$nestedVmPublicIP = $hs1VIP
		} else {
			$nestedVmSSHPort = 22
			$nestedVmPublicIP = $nestedVmIP
		}
		Write-LogInfo "The nested VM SSH port: $nestedVmSSHPort"
		Write-LogInfo "The nested VM public IP: $nestedVmPublicIP"

		New-ShellScriptFile -username $nestedVmUser | Out-Null
		Copy-RemoteFiles -uploadTo $nestedVmPublicIP -port $nestedVmSSHPort -files "$LogDir\StartFioTest.sh,$LogDir\ParseFioTestLogs.sh" -username $nestedVmUser -password $nestedVmPassword -upload

		$constantsFile = "$PWD\constants.sh"
		Copy-RemoteFiles -uploadTo $nestedVmPublicIP -port $nestedVmSSHPort -files "$constantsFile" -username $nestedVmUser -password $nestedVmPassword -upload

		Start-TestExecution -ip $nestedVmPublicIP -port $nestedVmSSHPort -username $nestedVmUser  -passwd $nestedVmPassword | Out-Null

		$files = "/home/$nestedVmUser/state.txt, /home/$nestedVmUser/TestExecutionConsole.log"
		Copy-RemoteFiles -download -downloadFrom $nestedVmPublicIP -port  $nestedVmSSHPort -username $nestedVmUser -password $nestedVmPassword -downloadTo $LogDir -files $files
		$finalStatus = Get-Content $LogDir\state.txt
		if ($finalStatus -imatch "TestFailed") {
			Write-LogErr "Test failed. Last known status : $currentStatus."
			$testResult = $resultFail
		} elseif ($finalStatus -imatch "TestAborted") {
			Write-LogErr "Test Aborted. Last known status : $currentStatus."
			$testResult = $resultAborted
		} elseif ($finalStatus -imatch "TestCompleted") {
			$testResult = $resultPass
		} elseif ($finalStatus -imatch "TestRunning") {
			Write-LogInfo "Powershell background job for test is completed but VM is reporting that test is still running. Please check $LogDir\TestExecutionConsole.txt"
			$testResult = $resultAborted
		}

		$files = "fioConsoleLogs.txt"
		Copy-RemoteFiles -download -downloadFrom  $nestedVmPublicIP -port $nestedVmSSHPort -username $nestedVmUser -password $nestedVmPassword  -downloadTo $LogDir -files $files
		if ($testResult -imatch $resultPass) {
			Remove-Item "$LogDir\*.csv" -Force | Out-Null
			$remoteFiles = "FIOTest-*.tar.gz,perf_fio.csv,nested_properties.csv,runlog.txt"
			Copy-RemoteFiles -download -downloadFrom $nestedVmPublicIP -files $remoteFiles -downloadTo $LogDir -port $nestedVmSSHPort -username $nestedVmUser -password $nestedVmPassword
			foreach ( $line in (Get-Content "$LogDir\perf_fio.csv" )) {
				if ($line -imatch "Max IOPS of each mode") {
					$maxIOPSforMode = $true
					$maxIOPSforBlockSize = $false
					$fioData = $false
				}
				if ($line -imatch "Max IOPS of each BlockSize") {
					$maxIOPSforMode = $false
					$maxIOPSforBlockSize = $true
					$fioData = $false
				}
				if ($line -imatch "Iteration,TestType,BlockSize") {
					$maxIOPSforMode = $false
					$maxIOPSforBlockSize = $false
					$fioData = $true
				}
				if ($maxIOPSforMode) {
					Add-Content -Value $line -Path $LogDir\maxIOPSforMode.csv
				}
				if ($maxIOPSforBlockSize) {
					Add-Content -Value $line -Path $LogDir\maxIOPSforBlockSize.csv
				}
				if ($fioData) {
					Add-Content -Value $line -Path $LogDir\fioData.csv
				}
			}

			Get-SQLQueryOfNestedHyperv -currentTestResult $currentTestResult -session $session -AllVMData $AllVMData
		}
	} catch {
		$errorMessage =  $_.Exception.Message
		$ErrorLine = $_.InvocationInfo.ScriptLineNumber
		Write-LogInfo "EXCEPTION : $errorMessage at line: $ErrorLine"
	} Finally {
		if ($session) {
			Remove-PSSession -Session $session | Out-Null
		}
		if (!$testResult) {
			$testResult = $resultAborted
		}
	}

	$resultArr += $testResult
	Write-LogInfo "Test result : $testResult"
	$currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
	return $currentTestResult
}

# Main Body
Main
