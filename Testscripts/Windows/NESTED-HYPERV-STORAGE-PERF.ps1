# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

function New-RaidOnL1 ($session, $interleave) {
	LogMsg "Create raid0 on level 1 with $interleave Interleave"
	Invoke-Command -Session $session -ScriptBlock {
		param($interleave)

		$poolName = "Raid0-Pool"
		$raidDiskName = "Raid0-Disk"

		$diskNumbers = (Get-Disk | Where-Object {$_.FriendlyName -eq 'Msft Virtual Disk'}).Number
		foreach ( $number in $diskNumbers )
		{
			set-disk $number -isOffline $true
		}

		$disks = Get-PhysicalDisk -CanPool  $true
		New-StoragePool -StorageSubSystemFriendlyName "Windows Storage*"  -FriendlyName $poolName -PhysicalDisks $disks
		New-VirtualDisk -FriendlyName $raidDiskName -StoragePoolFriendlyName $poolName  -Interleave $interleave -UseMaximumSize -ResiliencySettingName Simple
		$diskNumber = ( get-disk | Where-Object{ $_.FriendlyName -eq $raidDiskName } ).Number
		Set-Disk  $diskNumber -IsOffline $true
	} -ArgumentList $interleave
}

function New-NestedVM ($session, $vmMem, $osVHD, $vmName, $processors, $switchName) {
	LogMsg "Create the $vmName VM with mem:$vmMem, processors:$processors"
	Invoke-Command -Session $session -ScriptBlock {
			param($vmMem,$osVHD,$vmName,$processors,$switchName)

			$savePath = "C:\Users\"
			$currentVMOsVHDPath = $savePath + $vmName + ".vhd"

			New-VHD -ParentPath $osVHD -Path $currentVMOsVHDPath

			$NewVM = New-VM -Name $vmName -MemoryStartupBytes $vmMem -BootDevice VHD -VHDPath $currentVMOsVHDPath -Path $savePath -Generation 1 -Switch $switchName
			if ($?)
			{
				Set-VM -VM $NewVM -ProcessorCount $processors -StaticMemory -CheckpointType Disabled

				$diskNumbers = (Get-Disk | Where-Object {$_.FriendlyName -eq 'Msft Virtual Disk'}).Number
				foreach ( $number in $diskNumbers )
				{
					set-disk $number -isOffline $true
				}

				$diskNumbers = (Get-Disk | Where-Object {$_.OperationalStatus -eq 'offline'}).Number
				$count = 0
				foreach ( $lun in $diskNumbers )
				{
					"Add physical disk $($diskNumbers[$count]) to controller on virtual machine $vmName."
					$NewVM | Add-VMHardDiskDrive -DiskNumber $($diskNumbers[$count]) -ControllerType 'SCSI'
					$count ++
				}
			}

		} -ArgumentList $vmMem, $osVHD, $vmName, $processors, $switchName
}

function Get-NestedVMIPAdress ($session, $vmName) {
	#Start the nested vm if it's not running
	LogMsg "Get the IPv4 address of the nested VM $vmName"
	Invoke-Command -Session $session -ScriptBlock {
		param($vmName)

		$status = Get-VM -Name $vmName
		if ($($status.State) -ne "running")
		{
			Start-VM -Name $vmName
			Start-Sleep 10
		}
	} -ArgumentList $vmName

	$MaxCount = 20
	$i=0
	do
	{
		$i++
		Start-Sleep 30
		$VMNicProperties = Invoke-Command -Session $session -ScriptBlock {
			param($vmName)

			Get-VMNetworkAdapter -VMName $vmName
		}  -ArgumentList $vmName

		$nestedVmIP = $VMNicProperties.IPAddresses | Where-Object {$_ -imatch "\b(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(\.(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}\b"}
	}while(($i -lt $MaxCount) -and (!$nestedVmIP))

	return $nestedVmIP
}

function New-ShellScriptFile($LogDir,$username)
{
	$scriptContent = @"
echo nameserver 8.8.8.8 >> /etc/resolv.conf
chmod +x nested_kvm_perf_fio.sh
./nested_kvm_perf_fio.sh &> fioConsoleLogs.txt
. utils.sh
collect_VM_properties nested_properties.csv
"@

	$scriptContent2 = @"
chmod +x *.sh
cp fio_jason_parser.sh gawk JSON.awk /home/$username/FIOLog/jsonLog/
cd /home/$username/FIOLog/jsonLog/
bash fio_jason_parser.sh
cp perf_fio.csv /home/$username/
cd /home/$username/
chmod 666 perf_fio.csv

"@
	Set-Content "$LogDir\StartFioTest.sh" $scriptContent
	Set-Content "$LogDir\ParseFioTestLogs.sh" $scriptContent2
}

function Start-TestExecution ($ip, $port, $username, $passwd)
{
	RemoteCopy -uploadTo $ip -port $port -files $currentTestData.files -username $username -password $passwd -upload
	RunLinuxCmd -ip $ip -port $port -username $username -password $passwd -command "rm -f /home/$username/*.txt;rm -f /home/$username/*.log" -runAsSudo
	RunLinuxCmd -ip $ip -port $port -username $username -password $passwd -command "cp *.sh /root;touch /home/$username/state.txt" -runAsSudo
	RunLinuxCmd -ip $ip -port $port -username $username -password $passwd -command "chmod +x *.sh;chmod +x /root/*.sh" -runAsSudo
	LogMsg "Executing : StartFioTest.sh"
	$cmd = "/home/$username/StartFioTest.sh"
	RunLinuxCmd -ip $ip -port  $port -username $username -password $passwd -command $cmd -runAsSudo  -runMaxAllowedTime  24000  -RunInBackground
	$currentStatus = RunLinuxCmd -ip $ip -port  $port -username $username -password $passwd -command "cat /home/$username/state.txt"  -runAsSudo
	while ( $currentStatus -like "*TestRunning*" -or -not $currentStatus )
	{
		$currentStatus = RunLinuxCmd -ip $ip -port  $port -username $username -password $passwd -command "cat /home/$username/state.txt"  -runAsSudo
		LogMsg "Current test status : $currentStatus"
		WaitFor -seconds 30
	}

	LogMsg "Executing : ParseFioTestLogs.sh"
	$cmd = "/home/$username/ParseFioTestLogs.sh > /home/$username/TestExecutionConsole.log"
	RunLinuxCmd -ip $ip -port  $port -username $username -password $passwd -command $cmd -runAsSudo
}

function Send-ResultToDatabase ($xmlConfig, $logDir, $session)
{
	LogMsg "Uploading the test results.."
	$dataSource = $xmlConfig.config.$TestPlatform.database.server
	$DBuser = $xmlConfig.config.$TestPlatform.database.user
	$DBpassword = $xmlConfig.config.$TestPlatform.database.password
	$database = $xmlConfig.config.$TestPlatform.database.dbname
	$dataTableName = $xmlConfig.config.$TestPlatform.database.dbtable
	$TestCaseName = $xmlConfig.config.$TestPlatform.database.testTag
	if ($dataSource -And $DBuser -And $DBpassword -And $database -And $dataTableName)
	{
		Import-Csv -Path $LogDir\maxIOPSforMode.csv
		Import-Csv -Path $LogDir\maxIOPSforBlockSize.csv
		$fioDataCsv = Import-Csv -Path $LogDir\fioData.csv

		$HostType = $TestPlatform
		if ($TestPlatform -eq "hyperV")
		{
			$HostBy = $xmlConfig.config.Hyperv.Host.ServerName
			$HyperVMappedSizes = [xml](Get-Content .\XML\AzureVMSizeToHyperVMapping.xml)
			$L1GuestCpuNum = $HyperVMappedSizes.HyperV.$HyperVInstanceSize.NumberOfCores
			$L1GuestMemMB = [int]($HyperVMappedSizes.HyperV.$HyperVInstanceSize.MemoryInMB)
			$L1GuestSize = "$($L1GuestCpuNum)Cores $($L1GuestMemMB/1024)G"
			$HostOS	= (Get-WmiObject -Class Win32_OperatingSystem -ComputerName $xmlConfig.config.$TestPlatform.Host.ServerName).Version
		}
		else
		{
			$HostBy	= ($xmlConfig.config.$TestPlatform.General.Location).Replace('"','')
			$L1GuestSize = $AllVMData.InstanceSize
			$keys = "HostingSystemOsMajor", "HostingSystemOsMinor", "HostingSystemEditionId"
			$registryEntry =  'HKLM:\SOFTWARE\Microsoft\Virtual Machine\Guest\Parameters'
			$values = @()
			foreach ( $key in  $keys)
			{
				$val = Invoke-Command -Session $session -ScriptBlock {
					param($registryEntry, $key)
					(get-item $registryEntry).GetValue("$key")
				} -ArgumentList $registryEntry, $key
				$values += $val
			}
			$HostOS = [string]$values[0]+ "." + [string]$values[1] + "." + [string]$values[2]
		}
		$setupType = $currentTestData.setupType
		$count = 0
		foreach ($disk in $xmlConfig.config.$TestPlatform.Deployment.$setupType.ResourceGroup.VirtualMachine.DataDisk)
		{
			$disk_size = $disk.DiskSizeInGB
			$count ++
		}
		$DiskSetup = "$count SSD: $($disk_size)G"

		# Get L1 guest info
		$computerInfo = Invoke-Command -Session $session -ScriptBlock {Get-ComputerInfo}
		$L1GuestDistro	= $computerInfo.OsName
		$L1GuestKernelVersion = Get-Content "$LogDir\nested_properties.csv" | Select-String "Host Version"| ForEach-Object {$_ -replace ",Host Version,",""}
		$L1GuestOSType = "Windows"

		# Get L2 guest info
		$L2GuestDistro = Get-Content "$LogDir\nested_properties.csv" | Select-String "OS type"| ForEach-Object {$_ -replace ",OS type,",""}
		$L2GuestKernelVersion = Get-Content "$LogDir\nested_properties.csv" | Select-String "Kernel version"| ForEach-Object {$_ -replace ",Kernel version,",""}
		foreach ( $param in $currentTestData.TestParameters.param)
		{
			if ($param -match "NestedCpuNum")
			{
				$L2GuestCpuNum = [int]($param.split("=")[1])
			}
			if ($param -match "NestedMemMB")
			{
				$L2GuestMemMB = [int]($param.split("=")[1])
			}
			if ( $param -match "startThread" )
			{
				$startThread = [int]($param.split("=")[1])
			}
			if ( $param -match "maxThread" )
			{
				$maxThread = [int]($param.split("=")[1])
			}
			if ( $param -match "RaidOption" )
			{
				$RaidOption = $param.Replace("RaidOption=","").Replace("'","")
			}
		}
		$connectionString = "Server=$dataSource;uid=$DBuser; pwd=$DBpassword;Database=$database;Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"

		$SQLQuery = "INSERT INTO $dataTableName (TestCaseName,TestDate,HostType,HostBy,HostOS,L1GuestOSType,L1GuestDistro,L1GuestSize,L1GuestKernelVersion,L2GuestDistro,L2GuestKernelVersion,L2GuestCpuNum,L2GuestMemMB,DiskSetup,RaidOption,BlockSize_KB,QDepth,seq_read_iops,seq_read_lat_usec,rand_read_iops,rand_read_lat_usec,seq_write_iops,seq_write_lat_usec,rand_write_iops,rand_write_lat_usec) VALUES "

		for ( $QDepth = $startThread; $QDepth -le $maxThread; $QDepth *= 2 )
		{
			$seq_read_iops = [Float](($fioDataCsv |  Where-Object { $_.TestType -eq "read" -and  $_.Threads -eq "$QDepth"} | Select-Object ReadIOPS).ReadIOPS)
			$seq_read_lat_usec = [Float](($fioDataCsv |  Where-Object { $_.TestType -eq "read" -and  $_.Threads -eq "$QDepth"} | Select-Object MaxOfReadMeanLatency).MaxOfReadMeanLatency)

			$rand_read_iops = [Float](($fioDataCsv |  Where-Object { $_.TestType -eq "randread" -and  $_.Threads -eq "$QDepth"} | Select-Object ReadIOPS).ReadIOPS)
			$rand_read_lat_usec = [Float](($fioDataCsv |  Where-Object { $_.TestType -eq "randread" -and  $_.Threads -eq "$QDepth"} | Select-Object MaxOfReadMeanLatency).MaxOfReadMeanLatency)

			$seq_write_iops = [Float](($fioDataCsv |  Where-Object { $_.TestType -eq "write" -and  $_.Threads -eq "$QDepth"} | Select-Object WriteIOPS).WriteIOPS)
			$seq_write_lat_usec = [Float](($fioDataCsv |  Where-Object { $_.TestType -eq "write" -and  $_.Threads -eq "$QDepth"} | Select-Object MaxOfWriteMeanLatency).MaxOfWriteMeanLatency)

			$rand_write_iops = [Float](($fioDataCsv |  Where-Object { $_.TestType -eq "randwrite" -and  $_.Threads -eq "$QDepth"} | Select-Object WriteIOPS).WriteIOPS)
			$rand_write_lat_usec= [Float](($fioDataCsv |  Where-Object { $_.TestType -eq "randwrite" -and  $_.Threads -eq "$QDepth"} | Select-Object MaxOfWriteMeanLatency).MaxOfWriteMeanLatency)

			$BlockSize_KB= [Int]((($fioDataCsv |  Where-Object { $_.Threads -eq "$QDepth"} | Select-Object BlockSize)[0].BlockSize).Replace("K",""))

			$SQLQuery += "('$TestCaseName','$(Get-Date -Format yyyy-MM-dd)','$HostType','$HostBy','$HostOS','$L1GuestOSType','$L1GuestDistro','$L1GuestSize','$L1GuestKernelVersion','$L2GuestDistro','$L2GuestKernelVersion','$L2GuestCpuNum','$L2GuestMemMB','$DiskSetup','$RaidOption','$BlockSize_KB','$QDepth','$seq_read_iops','$seq_read_lat_usec','$rand_read_iops','$rand_read_lat_usec','$seq_write_iops','$seq_write_lat_usec','$rand_write_iops','$rand_write_lat_usec'),"
			LogMsg "Collected performace data for $QDepth QDepth."
		}

		$SQLQuery = $SQLQuery.TrimEnd(',')
		LogMsg "SQLQuery:"
		LogMsg "$SQLQuery"
		$connection = New-Object System.Data.SqlClient.SqlConnection
		$connection.ConnectionString = $connectionString
		$connection.Open()

		$command = $connection.CreateCommand()
		$command.CommandText = $SQLQuery

		$command.executenonquery()
		$connection.Close()
		LogMsg "Uploading the test results done!!"
	}
	else
	{
		LogMsg "Database details are not provided. Results will not be uploaded to database!!"
	}
}

function New-CustomScript( )
{
	LogMsg "Create the content of custom script"
	$customScriptName = "myCustomScript.ps1"
	$customScriptContent = @"
netsh advfirewall firewall add rule name="WinRM HTTP" dir=in action=allow protocol=TCP localport=5985 profile=public
"@

	Set-Content  "$LogDir\$customScriptName"  $customScriptContent

	$rgName = $AllVMData.ResourceGroupName
	$containerName = "vhds"
	$storageName = (Get-AzureRmStorageAccount -ResourceGroupName $rgName).StorageAccountName
	if( -not $storageName ){
		$randomNum = Get-Random -Maximum 999 -Minimum 100
		$storageName = "temp" + [string]$randomNum
		$location = $xmlConfig.config.Azure.General.Location
		New-AzureRmStorageAccount -ResourceGroupName $rgName -AccountName $storageName -Location $location -SkuName "Standard_GRS"   | Out-Null
	}
	$StorageKey = (Get-AzurermStorageAccountKey  -Name $storageName -ResourceGroupName $rgName).Value[0]
	$sourceContext = New-AzureStorageContext -StorageAccountName $storageName -StorageAccountKey $StorageKey
	$blobContainer = Get-AzureStorageContainer -Name $containerName -Context $sourceContext 2>$null
	if( $null -eq $blobContainer )
	{
		LogMsg "The container $containerName doesn't exist, so create it."
		New-AzureStorageContainer -Name $containerName -Context $sourceContext   | Out-Null
		Start-Sleep 3
		$blobContainer = Get-AzureStorageContainer -Name $containerName -Context $sourceContext
	}

	LogMsg "Upload the custom script to $blobContainer"
	Set-AzureStorageBlobContent -File "$LogDir\$customScriptName" -Container $containerName  -Context $sourceContext   | Out-Null

	$customScriptURI = $blobContainer.CloudBlobContainer.Uri.ToString() + "/" + $customScriptName
	return $customScriptURI
}

function Invoke-CustomScript($fileUri)
{
	LogMsg "Run custom script: $fileUri"
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
	$location = $xmlConfig.config.Azure.General.Location
	$sts=Set-AzureRmVMExtension -ResourceGroupName $rgName -Location $location -VMName $myVM  -Name $name -Publisher $publisher -ExtensionType $type  -TypeHandlerVersion "1.9"  -Settings $settings  -ProtectedSettings $proSettings
	if( $sts.IsSuccessStatusCode )
	{
	  LogMsg "Run custom script successfully."
	}
	else
	{
	  LogErr "Run custom script failed."
	}
}

function Get-OSvhd ($session, $srcPath, $dstPath) {
	LogMsg "Downloading vhd from $srcPath to $dstPath ..."
	if( $srcPath.Trim().StartsWith("http") ){
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
			do{
				if($lastStatus -ne $btjob.JobState) {
					$lastStatus = $btjob.JobState
				}

				if($lastStatus -like "*Error*") {
					Remove-BitsTransfer $btjob
					Write-Output "Error connecting $srcPath to download."
					return 1
				}
			} while ($lastStatus -ne "Transferring")

			do{
				Write-Output (Get-Date) $btjob.BytesTransferred $btjob.BytesTotal ($btjob.BytesTransferred/$btjob.BytesTotal*100)
				Start-Sleep -s 10
			} while ($btjob.BytesTransferred -lt $btjob.BytesTotal)

			Write-Output (Get-Date) $btjob.BytesTransferred $btjob.BytesTotal ($btjob.BytesTransferred/$btjob.BytesTotal*100)
			Complete-BitsTransfer $btjob
		}  -ArgumentList $srcPath, $dstPath
	}
	else
	{
		Copy-Item $srcPath -Destination $dstPath -ToSession $session
	}
}

function Install-Hyperv ($session) {
	LogMsg "Install Hyper-V and restart the host"
	Invoke-Command -Session $session -ScriptBlock { Install-WindowsFeature -Name Hyper-V -IncludeManagementTools -Restart }
	Start-Sleep 100
}

function New-NetworkSwitch ($session, $switchName)  {
	LogMsg "Start to create a network switch named $switchName"
	Invoke-Command -Session $session -ScriptBlock {
		param($switchName)
		$switchNames = (Get-VMSwitch).name
		foreach ( $vmswitchName in $switchNames )
		{
			remove-VMSwitch $vmswitchName -Force
		}

		$netAdapterNames  = (Get-NetAdapter).name
		foreach ( $netAdapterName in $netAdapterNames )
		{
			if( $netAdapterName -like "*vEthernet*" )
			{
				continue
			}
			else
			{
				New-VMSwitch -name $switchName -NetAdapterName $netAdapterName -AllowManagementOS $true
				break
			}
		}

	}  -ArgumentList $switchName
}

function New-NAT ($session, $switchName, $natName) {
	LogMsg "Start to create a network NAT named $natName"
	Invoke-Command -Session $session -ScriptBlock {
		param($switchName, $natName)
		New-VMSwitch -Name $switchName -SwitchType Internal
		$interfaceIndex =  (Get-NetAdapter -Name "*$switchName*").ifindex
		New-NetIPAddress -IPAddress "192.168.0.1" -PrefixLength 24 -InterfaceIndex $interfaceIndex
		New-NetNat -Name $natName -InternalIPInterfaceAddressPrefix "192.168.0.0/24"
	} -ArgumentList $switchName, $natName

	LogMsg "Create the network NAT named $natName completes."
}

function Add-NestedNatStaticMapping ($session, $natName, $ip_addr, $internalPort, $externalPort) {
	LogMsg "Mapping $ip_addr internal port $internalPort external port $externalPort "
	Invoke-Command -Session $session -ScriptBlock {
		param($natName, $ip_addr, $internalPort, $externalPort)
		Add-NetNatStaticMapping -NatName $natName -Protocol TCP -ExternalIPAddress "0.0.0.0" -InternalIPAddress $ip_addr -InternalPort $internalPort -ExternalPort $externalPort
	} -ArgumentList $natName, $ip_addr, $internalPort, $externalPort
}

function Main()
{
	$currentTestResult = CreateTestResultObject
	$resultArr = @()
	$testResult = $resultAborted
	try
	{
		$hs1VIP = $AllVMData.PublicIP

		# Get the test parameters
		foreach ( $param in $currentTestData.TestParameters.param)
		{

			if ( $param -imatch "RaidOption" )
			{
				$RaidOption = $param.Replace("RaidOption=","").Replace("'","")
			}
			if ( $param -imatch "NestedCpuNum=" )
			{
					$nestedCPUs = [int]$param.Replace("NestedCpuNum=","")
			}
			if ( $param -imatch "NestedMemMB=" )
			{
					$nestedMemMB = [int]$param.Replace("NestedMemMB=","")
			}
			if ( $param -imatch "NestedUser=" )
			{
					$nestedVmUser = $param.Replace("NestedUser=","").Replace("'","")
			}
			if ( $param -imatch "NestedUserPassword=" )
			{
				$nestedVmPassword = $param.Replace("NestedUserPassword=","").Replace("'","")
			}
			if ( $param -imatch "NestedImageUrl=" )
			{
				$nestedVhdPath = $param.Replace("NestedImageUrl=","").Replace("'","").Trim()
			}
			if ( $param -imatch "Interleave=" )
			{
				$interleave = [int]$param.Replace("Interleave=","")
			}
		}

		if ($testPlatform -eq "Azure") {
			$customScriptUri = New-CustomScript
			Invoke-CustomScript -fileUri $customScriptUri
		}

		# Create remote session
		$cred = Get-Cred -user $user -password $password
		if ($testPlatform -eq "Azure") {
			$sessionPort = 5985
			$connectionURL = "http://${hs1VIP}:${sessionPort}"
			LogMsg "Session connection URL: $connectionURL"
			$session = New-PSSession -ConnectionUri $connectionURL -Credential $cred -SessionOption (New-PSSessionOption -SkipCACheck -SkipCNCheck -SkipRevocationCheck)
		}
		else {
			$session = New-PSSession -ComputerName $hs1VIP -Credential $cred
		}

		if( $RaidOption -eq "RAID in L1" )
		{
			New-RaidOnL1  -session $session -interleave $interleave
		}

		# Download L2 OS vhd
		$curtime = ([string]((Get-Date).Ticks / 1000000)).Split(".")[0]
		$nestOSVHD = "C:\Users\test_" + "$curtime" +".vhd"
		Get-OSvhd -session $session -srcPath $nestedVhdPath -dstPath $nestOSVHD

		if ($testPlatform -eq "Azure") {
			try{
				Install-Hyperv -session $session
			}
			catch
			{
				# Ignore the exception caused by restart the vm
			}

			#Installation of Hyper-v will restart the vm, so renew the session
			$session = New-PSSession -ConnectionUri $connectionURL -Credential $cred -SessionOption (New-PSSessionOption -SkipCACheck -SkipCNCheck -SkipRevocationCheck)
		}

		$nestedVMMemory = $nestedMemMB * 1024 * 1024
		$nestedVMName = "LinuxNestedVM"
		$nestedVMSwithName = "MySwitch"
		$nestedNATName = "MyNATNet"

		if ($testPlatform -eq "Azure") {
			New-NAT -session $session -switchName $nestedVMSwithName -natName $nestedNATName
		}
		else {
			New-NetworkSwitch -session $session -switchName $nestedVMSwithName
		}

		New-NestedVM -session $session -vmMem  $nestedVMMemory  -osVHD $nestOSVHD -vmName $nestedVMName -processors $nestedCPUs -switchName $nestedVMSwithName

		$nestedVmIP = Get-NestedVMIPAdress -session $session  -vmName $nestedVMName

		if ($testPlatform -eq "Azure") {
			$nestedVmSSHPort = 222
			Add-NestedNatStaticMapping  -session $session  -natName $nestedNATName -ip_addr $nestedVmIP  -internalPort 22 -externalPort $nestedVmSSHPort
			$nestedVmPublicIP = $hs1VIP
		}
		else
		{
			$nestedVmSSHPort = 22
			$nestedVmPublicIP = $nestedVmIP
		}
		LogMsg "The nested VM SSH port: $nestedVmSSHPort"
		LogMsg "The nested VM public IP: $nestedVmPublicIP"

		New-ShellScriptFile -logDir $LogDir  -username $nestedVmUser
		RemoteCopy -uploadTo $nestedVmPublicIP -port $nestedVmSSHPort -files ".\$LogDir\StartFioTest.sh,.\$LogDir\ParseFioTestLogs.sh" -username $nestedVmUser -password $nestedVmPassword -upload

		$constantsFile = "$PWD\constants.sh"
        RemoteCopy -uploadTo $nestedVmPublicIP -port $nestedVmSSHPort -files "$constantsFile" -username $nestedVmUser -password $nestedVmPassword -upload

		Start-TestExecution -ip $nestedVmPublicIP -port $nestedVmSSHPort -username $nestedVmUser  -passwd $nestedVmPassword

		$files = "/home/$nestedVmUser/state.txt, /home/$nestedVmUser/TestExecutionConsole.log"
		RemoteCopy -download -downloadFrom $nestedVmPublicIP -port  $nestedVmSSHPort -username $nestedVmUser -password $nestedVmPassword -downloadTo $LogDir -files $files
		$finalStatus = Get-Content $LogDir\state.txt
		if ( $finalStatus -imatch "TestFailed")
		{
			LogErr "Test failed. Last known status : $currentStatus."
			$testResult = $resultFail
		}
		elseif ( $finalStatus -imatch "TestAborted")
		{
			LogErr "Test Aborted. Last known status : $currentStatus."
			$testResult = $resultAborted
		}
		elseif ( $finalStatus -imatch "TestCompleted")
		{
			$testResult = $resultPass
		}
		elseif ( $finalStatus -imatch "TestRunning")
		{
			LogMsg "Powershell background job for test is completed but VM is reporting that test is still running. Please check $LogDir\TestExecutionConsole.txt"
			$testResult = $resultAborted
		}

		$files = "fioConsoleLogs.txt"
		RemoteCopy -download -downloadFrom  $nestedVmPublicIP -port $nestedVmSSHPort -username $nestedVmUser -password $nestedVmPassword  -downloadTo $LogDir -files $files
		$CurrentTestResult.TestSummary += CreateResultSummary -testResult $testResult -metaData "" -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
		if ($testResult -imatch $resultPass)
		{
			Remove-Item "$LogDir\*.csv" -Force
			$remoteFiles = "FIOTest-*.tar.gz,perf_fio.csv,nested_properties.csv,runlog.txt"
			RemoteCopy -download -downloadFrom $nestedVmPublicIP -files $remoteFiles -downloadTo $LogDir -port $nestedVmSSHPort -username $nestedVmUser -password $nestedVmPassword
			$checkValues = "$resultPass,$resultFail,$resultAborted"
			$CurrentTestResult.TestSummary += CreateResultSummary -testResult $testResult -metaData "" -checkValues $checkValues -testName $currentTestData.testName
			foreach($line in (Get-Content "$LogDir\perf_fio.csv"))
			{
				if ( $line -imatch "Max IOPS of each mode" )
				{
					$maxIOPSforMode = $true
					$maxIOPSforBlockSize = $false
					$fioData = $false
				}
				if ( $line -imatch "Max IOPS of each BlockSize" )
				{
					$maxIOPSforMode = $false
					$maxIOPSforBlockSize = $true
					$fioData = $false
				}
				if ( $line -imatch "Iteration,TestType,BlockSize" )
				{
					$maxIOPSforMode = $false
					$maxIOPSforBlockSize = $false
					$fioData = $true
				}
				if ( $maxIOPSforMode )
				{
					Add-Content -Value $line -Path $LogDir\maxIOPSforMode.csv
				}
				if ( $maxIOPSforBlockSize )
				{
					Add-Content -Value $line -Path $LogDir\maxIOPSforBlockSize.csv
				}
				if ( $fioData )
				{
					Add-Content -Value $line -Path $LogDir\fioData.csv
				}
			}

			Send-ResultToDatabase -xmlConfig $xmlConfig -logDir $LogDir -session $session
		}
	}
	catch
	{
		$errorMessage =  $_.Exception.Message
		$ErrorLine = $_.InvocationInfo.ScriptLineNumber
		LogMsg "EXCEPTION : $errorMessage at line: $ErrorLine"
	}
	Finally
	{
		if($session){
			Remove-PSSession -Session $session
		}
		if(!$testResult){
			$testResult = $resultAborted
		}
	}

	$resultArr += $testResult
	LogMsg "Test result : $testResult"
	$currentTestResult.TestResult = GetFinalResultHeader -resultarr $resultArr
	return $currentTestResult.TestResult
}

# Main Body
Main
