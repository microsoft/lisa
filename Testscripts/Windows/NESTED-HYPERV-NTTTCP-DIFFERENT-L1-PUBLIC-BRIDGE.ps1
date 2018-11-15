# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

$testScript = "nested_hyperv_ntttcp_different_l1_public_bridge.sh"

function Start-TestExecution ($ip, $port, $cmd) {
	RemoteCopy -uploadTo $ip -port $port -files $currentTestData.files -username $nestedUser -password $nestedPassword -upload
	RunLinuxCmd -username $nestedUser -password $nestedPassword -ip $ip -port $port -command "chmod +x *" -runAsSudo
	LogMsg "Executing : ${cmd}"
	$testJob = RunLinuxCmd -username $nestedUser -password $nestedPassword -ip $ip -port $port -command $cmd -runAsSudo -RunInBackground
	while ( (Get-Job -Id $testJob).State -eq "Running" ) {
		$currentStatus = RunLinuxCmd -username $nestedUser -password $nestedPassword -ip $ip -port $port -command "cat /home/$nestedUser/state.txt"
		LogMsg "Current Test Status : $currentStatus"
		WaitFor -seconds 20
	}
}

function Download-OSvhd ($session, $srcPath, $dstPath) {
	LogMsg "Downloading vhd from $srcPath to $dstPath ..."
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

function Send-ResultToDatabase ($xmlConfig, $logDir) {
	LogMsg "Uploading the test results.."
	$dataSource = $xmlConfig.config.$TestPlatform.database.server
	$user = $xmlConfig.config.$TestPlatform.database.user
	$password = $xmlConfig.config.$TestPlatform.database.password
	$database = $xmlConfig.config.$TestPlatform.database.dbname
	$dataTableName = $xmlConfig.config.$TestPlatform.database.dbtable
	$TestCaseName = $xmlConfig.config.$TestPlatform.database.testTag
	if ($dataSource -And $user -And $password -And $database -And $dataTableName)
	{
		# Get host info
		$HostType	= $xmlConfig.config.CurrentTestPlatform
		$HostBy	= $TestLocation
		$HostOS	= (Get-WmiObject -Class Win32_OperatingSystem -ComputerName $xmlConfig.config.$TestPlatform.Hosts.ChildNodes[0].ServerName).Version

		# Get L1 guest info
		$L1GuestKernelVersion = Get-Content "$LogDir\nested_properties.csv" | Select-String "Host Version"| ForEach-Object{$_ -replace ",Host Version,",""}
		$computerInfo = Invoke-Command -ComputerName $hs1VIP -ScriptBlock {Get-ComputerInfo} -Credential $cred
		$L1GuestDistro	= $computerInfo.OsName

		$L1GuestOSType	= "Windows"
		$HyperVMappedSizes = [xml](Get-Content .\XML\AzureVMSizeToHyperVMapping.xml)
		$L1GuestCpuNum = $HyperVMappedSizes.HyperV.$HyperVInstanceSize.NumberOfCores
		$L1GuestMemMB = $HyperVMappedSizes.HyperV.$HyperVInstanceSize.MemoryInMB
		$L1GuestSize = $L1GuestCpuNum.ToString() +"Cores "+($L1GuestMemMB/1024).ToString()+"G"


		# Get L2 guest info
		$L2GuestDistro	= Get-Content "$LogDir\nested_properties.csv" | Select-String "OS type"| ForEach-Object{$_ -replace ",OS type,",""}
		$L2GuestKernelVersion	= Get-Content "$LogDir\nested_properties.csv" | Select-String "Kernel version"| ForEach-Object{$_ -replace ",Kernel version,",""}
		$flag=1
		if($TestLocation.split(',').Length -eq 2)
		{
			$flag=0
		}
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
		}

		$IPVersion = "IPv4"
		$ProtocolType = "TCP"
		$connectionString = "Server=$dataSource;uid=$user; pwd=$password;Database=$database;Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
		$LogContents = Get-Content -Path "$LogDir\report.log"
		$SQLQuery = "INSERT INTO $dataTableName (TestCaseName,TestDate,HostType,HostBy,HostOS,L1GuestOSType,L1GuestDistro,L1GuestSize,L1GuestKernelVersion,L2GuestDistro,L2GuestKernelVersion,L2GuestMemMB,L2GuestCpuNum,IPVersion,ProtocolType,NumberOfConnections,Throughput_Gbps,Latency_ms,TestPlatform,DataPath,SameHost) VALUES "

		for($i = 1; $i -lt $LogContents.Count; $i++)
		{
			$Line = $LogContents[$i].Trim() -split '\s+'
			$SQLQuery += "('$TestCaseName','$(Get-Date -Format yyyy-MM-dd)','$HostType','$HostBy','$HostOS','$L1GuestOSType','$L1GuestDistro','$L1GuestSize','$L1GuestKernelVersion','$L2GuestDistro','$L2GuestKernelVersion','$L2GuestMemMB','$L2GuestCpuNum','$IPVersion','$ProtocolType',$($Line[0]),$($Line[1]),$($Line[2]),'$HostType','Synthetic','$flag'),"
		}
		$SQLQuery = $SQLQuery.TrimEnd(',')
		LogMsg $SQLQuery

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
		LogMsg "Database details are not provided. Results will not be uploaded to database!"
	}
}

function CreateNestedVMNode()
{
	$objNode = New-Object -TypeName PSObject
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name PublicIP -Value $null -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name RoleName -Value $null -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name SSHPort -Value 22 -Force
	return $objNode
}

function Main () {
	$CurrentTestResult = CreateTestResultObject
	$testResult = $resultAborted
	$resultArr = @()
	$IP_MATCH = "\b(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(\.(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}\b"
	try
	{
		$cred = Get-Cred $user $password
		foreach($vm in $AllVMData)
		{
			if($vm.RoleName.Contains("server"))
			{
				$hs1VIP = $vm.PublicIP
			}
			if($vm.RoleName.Contains("client"))
			{
				$hs2VIP = $vm.PublicIP
			}
			LogMsg "Install Hyper-V role on $($vm.RoleName), IP - $($vm.PublicIP)"
			Invoke-Command -ComputerName $vm.PublicIP -ScriptBlock {Install-WindowsFeature -Name Hyper-V -ComputerName localhost -IncludeManagementTools} -Credential $cred
			LogMsg "Turn off firewall for $($vm.RoleName), IP - $($vm.PublicIP) to prepare running test"
			Invoke-Command -ComputerName $vm.PublicIP -ScriptBlock {Set-NetFirewallProfile -Profile Domain,Public,Private -Enabled False} -Credential $cred
		}

		LogMsg "Restart VMs to make sure Hyper-V install completely"
		RestartAllHyperVDeployments -allVMData $AllVMData

		start-sleep 20
		$serverSession = New-PSSession -ComputerName $hs1VIP -Credential $cred
		$clientSession = New-PSSession -ComputerName $hs2VIP -Credential $cred

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
			if ($param -match "NestedImageUrl")
			{
				$L2ImageUrl = $param.split("=")[1]
			}
			if ($param -match "NestedUser=")
			{
				$nestedUser = $param.split("=")[1]
			}
			if ($param -match "NestedUserPassword")
			{
				$nestedPassword = $param.split("=")[1].Split("'")[1]
			}
		}

		if( $L2ImageUrl.Trim().StartsWith("http") ){
			$curtime = ([string]((Get-Date).Ticks / 1000000)).Split(".")[0]
			$nestOSVHD = "C:\Users\test_" + "$curtime" +".vhd"
			Download-OSvhd -session $serverSession -srcPath $L2ImageUrl -dstPath $nestOSVHD
			Download-OSvhd -session $clientSession -srcPath $L2ImageUrl -dstPath $nestOSVHD
		}
		else {
			$nestOSVHD = $L2ImageUrl
		}

		$constantsFile = "$PWD\constants.sh"
		$allDeployedNestedVMs = @()
		$nestVMSSHPort=22
		foreach($vm in $AllVMData)
		{
			$IPAddresses = ""
			$output = ""
			Invoke-Command -ComputerName $vm.PublicIP -ScriptBlock {
				param([Int32]$CurrentVMCpu, [Int64]$CurrentVMMemory, $OsVHD="")
				$externalSwitchName = "External"
				$nosriovSwitchName = "NonSriov"
				$vmName = "test"

				$adapters = Get-NetAdapter
				foreach($adapter in $adapters)
				{
					if($adapter.LinkSpeed.ToString().Contains("10"))
					{
						New-VMSwitch  -Name $externalSwitchName -NetAdapterName $adapter.Name
					}
					if($adapter.LinkSpeed.ToString().Contains("40"))
					{
						New-VMSwitch  -Name "NonSriov" -NetAdapterName $adapter.Name
					}
				}

				$savePath = "C:\Users\"
				$CurrentVMOsVHDPath = $savePath + $vmName + ".vhd"
				New-VHD -ParentPath "$OsVHD" -Path $CurrentVMOsVHDPath

				$CurrentVMMemory = [Int64]$CurrentVMMemory * 1024 * 1024
				$NewVM = New-VM -Name $vmName -MemoryStartupBytes $CurrentVMMemory -BootDevice VHD -VHDPath $CurrentVMOsVHDPath -Generation 1 -Switch $externalSwitchName

				Add-VMNetworkAdapter -VMName $vmName -SwitchName $nosriovSwitchName
				Set-VM -VM $NewVM -ProcessorCount $CurrentVMCpu -StaticMemory -CheckpointType Disabled

				Start-VM -Name $vmName

				$VMNicProperties= Get-VMNetworkAdapter -VMName $vmName

				return $VMNicProperties.IPAddresses | Where-Object {$_ -imatch $IP_MATCH}
			} -Credential $cred -ArgumentList $L2GuestCpuNum,$L2GuestMemMB,$nestOSVHD

			$output = Invoke-Command -ComputerName $vm.PublicIP -ScriptBlock {
				$vmName = "test"
				Get-VMNetworkAdapter -VMName $vmName
			} -Credential $cred

			$IPAddresses = $output.IPAddresses | Where-Object {$_ -imatch $IP_MATCH}

			RunLinuxCmd -username $nestedUser -password $nestedPassword -ip $IPAddresses -port $nestVMSSHPort -command "echo $($vm.RoleName) > /etc/hostname" -runAsSudo -maxRetryCount 5
			RemoteCopy -uploadTo $IPAddresses -port $nestVMSSHPort -files "$constantsFile" -username $nestedUser -password $nestedPassword -upload
			RunLinuxCmd -username $nestedUser -password $nestedPassword -ip $IPAddresses -port $nestVMSSHPort -command "reboot" -runAsSudo -RunInBackGround
		}

		foreach($vm in $AllVMData)
		{
			$IPAddresses = ""
			$output = ""
			$RetryCount = 20
			$CurrentRetryAttempt=0
			do
			{
				$CurrentRetryAttempt++
				Start-Sleep 5
				LogMsg "    [$CurrentRetryAttempt/$RetryCount] : nested vm on $($vm.RoleName) : Waiting for IP address ..."
				$output = Invoke-Command -ComputerName $vm.PublicIP -ScriptBlock {
				$vmName = "test"
				Get-VMNetworkAdapter -VMName $vmName
				} -Credential $cred
				$IPAddresses = $output.IPAddresses | Where-Object {$_ -imatch $IP_MATCH}
			}while(($CurrentRetryAttempt -lt $RetryCount) -and (!$IPAddresses))

			$NestedVMNode = CreateNestedVMNode
			$NestedVMNode.PublicIP = $IPAddresses
			if($vm.RoleName.Contains("server"))
			{
				$NestedVMNode.RoleName = "ntttcp-server"
				$nttcpServerIP = $IPAddresses
			}
			if($vm.RoleName.Contains("client"))
			{
				$NestedVMNode.RoleName = "ntttcp-client"
				$nttcpClientIP = $IPAddresses
			}
			$allDeployedNestedVMs += $NestedVMNode
			$NestedVMNode = ""
		}
		Set-Variable -Name IsWindows -Value $false -Scope Global
		isAllSSHPortsEnabledRG $allDeployedNestedVMs
		Set-Variable -Name IsWindows -Value $true -Scope Global

		Remove-PSSession -Session $serverSession
		Remove-PSSession -Session $clientSession

		RemoteCopy -uploadTo $nttcpServerIP -port $nestVMSSHPort -files $currentTestData.files -username $nestedUser -password $nestedPassword -upload
		RunLinuxCmd -username $nestedUser -password $nestedPassword -ip $nttcpServerIP -port $nestVMSSHPort -command "chmod +x *" -runAsSudo
		$cmd = "/home/$nestedUser/${testScript} -role server -logFolder /home/$nestedUser > /home/$nestedUser/TestExecutionConsole.log"
		LogMsg "Executing : $($cmd)"
		RunLinuxCmd -username $nestedUser -password $nestedPassword -ip $nttcpServerIP -port $nestVMSSHPort -command $cmd -runAsSudo

		$cmd = "/home/$nestedUser/${testScript} -role client -logFolder /home/$nestedUser > /home/$nestedUser/TestExecutionConsole.log"
		Start-TestExecution -ip $nttcpClientIP -port $nestVMSSHPort -cmd $cmd

		# Download test logs
		RemoteCopy -download -downloadFrom $nttcpClientIP -files "/home/$nestedUser/state.txt, /home/$nestedUser/TestExecutionConsole.log" -downloadTo $LogDir -port $nestVMSSHPort -username $nestedUser -password $nestedPassword
		$finalStatus = Get-Content $LogDir\state.txt
		if ($finalStatus -imatch "TestFailed")
		{
			LogErr "Test failed. Last known status : $currentStatus."
			$testResult = $resultFail
		}
		elseif ($finalStatus -imatch "TestAborted")
		{
			LogErr "Test Aborted. Last known status : $currentStatus."
			$testResult = $resultAborted
		}
		elseif ($finalStatus -imatch "TestCompleted")
		{
			$testResult = $resultPass
		}
		elseif ($finalStatus -imatch "TestRunning")
		{
			LogMsg "Powershell backgroud job for test is completed but VM is reporting that test is still running. Please check $LogDir\zkConsoleLogs.txt"
			$testResult = $resultAborted
		}

		RemoteCopy -download -downloadFrom $nttcpClientIP -files "/home/$nestedUser/nested_properties.csv" -downloadTo $LogDir -port $nestVMSSHPort -username $nestedUser -password $nestedPassword

		if ($testResult -imatch $resultPass)
		{
			RemoteCopy -download -downloadFrom $nttcpClientIP -files "/home/$nestedUser/ntttcpConsoleLogs, /home/$nestedUser/ntttcpTest.log" -downloadTo $LogDir -port $nestVMSSHPort -username $nestedUser -password $nestedPassword
			RemoteCopy -download -downloadFrom $nttcpClientIP -files "/home/$nestedUser/nested_properties.csv, /home/$nestedUser/report.log" -downloadTo $LogDir -port $nestVMSSHPort -username $nestedUser -password $nestedPassword
			RemoteCopy -download -downloadFrom $nttcpClientIP -files "/home/$nestedUser/ntttcp-test-logs-receiver.tar, /home/$nestedUser/ntttcp-test-logs-sender.tar" -downloadTo $LogDir -port $nestVMSSHPort -username $nestedUser -password $nestedPassword

			$ntttcpReportLog = Get-Content -Path "$LogDir\report.log"
			if (!$ntttcpReportLog)
			{
				$testResult = $resultFail
				throw "Invalid NTTTCP report file"
			}
			$uploadResults = $true
			$checkValues = "$resultPass,$resultFail,$resultAborted"
			foreach ( $line in $ntttcpReportLog ) {
				if ( $line -imatch "test_connections" ){
					continue;
				}
				try
				{
					$splits = $line.Trim() -split '\s+'
					$testConnections = $splits[0]
					$throughputGbps = $splits[1]
					$cyclePerByte = $splits[2]
					$averageTcpLatency = $splits[3]
					$metadata = "Connections=$testConnections"
					$connResult = "throughput=$throughputGbps`Gbps cyclePerBytet=$cyclePerByte Avg_TCP_lat=$averageTcpLatency"
					$currentTestResult.TestSummary +=  CreateResultSummary -testResult $connResult -metaData $metaData -checkValues $checkValues -testName $currentTestData.testName
					if ([string]$throughputGbps -eq "0.00")
					{
						$testResult = $resultFail
						$uploadResults = $false
					}
				}
				catch
				{
					$currentTestResult.TestSummary +=  CreateResultSummary -testResult "Error in parsing logs." -metaData "NTTTCP" -checkValues $checkValues -testName $currentTestData.testName
				}
			}

			LogMsg $currentTestResult.TestSummary
			if (!$uploadResults) {
				LogMsg "Zero throughput for some connections, results will not be uploaded to database!"
			}
			else {
				Send-ResultToDatabase -xmlConfig $xmlConfig -logDir $LogDir
			}
		}
	}
	catch
	{
		$errorMessage =  $_.Exception.Message
		LogMsg "EXCEPTION : $errorMessage"
	}

	$resultArr += $testResult
	LogMsg "Test result : $testResult"
	$currentTestResult.TestResult = GetFinalResultHeader -resultarr $resultArr
	return $currentTestResult.TestResult
}

Main