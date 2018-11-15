# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

$testScript = "nested_kvm_lagscope_different_l1_public_bridge.sh"

function Start-TestExecution ($ip, $port, $cmd) {
	LogMsg "Executing : ${cmd}"
	$testJob = RunLinuxCmd -username $user -password $password -ip $ip -port $port -command $cmd -runAsSudo -RunInBackground
	while ((Get-Job -Id $testJob).State -eq "Running" ) {
		$currentStatus = RunLinuxCmd -username $user -password $password -ip $ip -port $port -command "cat /home/$user/state.txt"
		LogMsg "Current Test Status : $currentStatus"
		WaitFor -seconds 20
	}
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
		$HostOS	= Get-Content "$LogDir\VM_properties.csv" | Select-String "Host Version"| Foreach-Object{$_ -replace ",Host Version,",""}

		# Get L1 guest info
		$L1GuestDistro	= Get-Content "$LogDir\VM_properties.csv" | Select-String "OS type"| Foreach-Object{$_ -replace ",OS type,",""}
		$L1GuestOSType	= "Linux"
		$HyperVMappedSizes = [xml](Get-Content .\XML\AzureVMSizeToHyperVMapping.xml)
		$L1GuestCpuNum = $HyperVMappedSizes.HyperV.$HyperVInstanceSize.NumberOfCores
		$L1GuestMemMB = $HyperVMappedSizes.HyperV.$HyperVInstanceSize.MemoryInMB

		$L1GuestSize = $L1GuestCpuNum.ToString() +"Cores "+($L1GuestMemMB/1024).ToString()+"G"
		$L1GuestKernelVersion	= Get-Content "$LogDir\VM_properties.csv" | Select-String "Kernel version"| Foreach-Object{$_ -replace ",Kernel version,",""}

		# Get L2 guest info
		$L2GuestDistro	= Get-Content "$LogDir\nested_properties.csv" | Select-String "OS type"| Foreach-Object{$_ -replace ",OS type,",""}
		$L2GuestKernelVersion	= Get-Content "$LogDir\nested_properties.csv" | Select-String "Kernel version"| Foreach-Object{$_ -replace ",Kernel version,",""}
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
			if ($param -match "NestedNetDevice")
			{
				$KvmNetDevice = $param.split("=")[1]
			}
		}

		$IPVersion = "IPv4"
		$ProtocolType = "TCP"
		$connectionString = "Server=$dataSource;uid=$user; pwd=$password;Database=$database;Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
		$LogContents = Get-Content -Path "$LogDir\report.log"
		$SQLQuery = "INSERT INTO $dataTableName (TestCaseName,TestDate,HostType,HostBy,HostOS,L1GuestOSType,L1GuestDistro,L1GuestSize,L1GuestKernelVersion,L2GuestDistro,L2GuestKernelVersion,L2GuestMemMB,L2GuestCpuNum,KvmNetDevice,IPVersion,ProtocolType,NumberOfConnections,Throughput_Gbps,Latency_ms,TestPlatform,DataPath,SameHost) VALUES "

		for($i = 1; $i -lt $LogContents.Count; $i++)
		{
			$Line = $LogContents[$i].Trim() -split '\s+'
			$SQLQuery += "('$TestCaseName','$(Get-Date -Format yyyy-MM-dd)','$HostType','$HostBy','$HostOS','$L1GuestOSType','$L1GuestDistro','$L1GuestSize','$L1GuestKernelVersion','$L2GuestDistro','$L2GuestKernelVersion','$L2GuestMemMB','$L2GuestCpuNum','$KvmNetDevice','$IPVersion','$ProtocolType',$($Line[0]),$($Line[1]),$($Line[2]),'$HostType','Synthetic','$flag'),"
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

function Main () {
	$currentTestResult = CreateTestResultObject
	$resultArr = @()
	$testResult = $resultAborted
	try
	{
		foreach($vm in $AllVMData)
		{
			if($vm.RoleName.Contains("server"))
			{
				$hs1VIP = $vm.PublicIP
				$hs1vm1sshport = $vm.SSHPort
			}
			if($vm.RoleName.Contains("client"))
			{
				$hs2VIP = $vm.PublicIP
				$hs2vm1sshport = $vm.SSHPort
			}
		}

		foreach ($param in $currentTestData.TestParameters.param) {
			if ($param -imatch "pingIteration") {
				$pingIteration=$param.Trim().Replace("pingIteration=","")
			}
		}

		$cmd = "/home/$user/${testScript} -role server -level1ClientIP $hs2VIP -level1User $user -level1Password $password -level1Port $hs2vm1sshport -logFolder /home/$user > /home/$user/TestExecutionConsole.log"
		Start-TestExecution -ip $hs1VIP -port $hs1vm1sshport -cmd $cmd

		$cmd = "/home/$user/${testScript} -role client -logFolder /home/$user > /home/$user/TestExecutionConsole.log"
		Start-TestExecution -ip $hs2VIP -port $hs2vm1sshport -cmd $cmd

		# Download test logs
		RemoteCopy -download -downloadFrom $hs2VIP -files "/home/$user/state.txt, /home/$user/${testScript}.log, /home/$user/TestExecutionConsole.log" -downloadTo $LogDir -port $hs2vm1sshport -username $user -password $password
		$finalStatus = Get-Content $LogDir\state.txt

		RunLinuxCmd -username $user -password $password -ip $hs2VIP -port $hs2vm1sshport -command ". utils.sh && collect_VM_properties" -runAsSudo
		RemoteCopy -downloadFrom $hs2VIP -port $hs2vm1sshport -username $user -password $password -download -downloadTo $LogDir -files "/home/$user/lagscope-n$pingIteration-output.txt,/home/$user/nested_properties.csv,/home/$user/VM_properties.csv"

		$testSummary = $null
		$lagscopeReportLog = Get-Content -Path "$LogDir\lagscope-n$pingIteration-output.txt"
		LogMsg $lagscopeReportLog
		#endregion

		try {
			$matchLine= (Select-String -Path "$LogDir\lagscope-n$pingIteration-output.txt" -Pattern "Average").Line
			$minimumLat = $matchLine.Split(",").Split("=").Trim().Replace("us","")[1]
			$maximumLat = $matchLine.Split(",").Split("=").Trim().Replace("us","")[3]
			$averageLat = $matchLine.Split(",").Split("=").Trim().Replace("us","")[5]

			$currentTestResult.TestSummary += CreateResultSummary -testResult $minimumLat -metaData "Minimum Latency" -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
			$currentTestResult.TestSummary += CreateResultSummary -testResult $maximumLat -metaData "Maximum Latency" -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
			$currentTestResult.TestSummary += CreateResultSummary -testResult $averageLat -metaData "Average Latency" -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
		} catch {
			$currentTestResult.TestSummary += CreateResultSummary -testResult "Error in parsing logs." -metaData "LAGSCOPE" -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
		}

		if ($finalStatus -imatch "TestFailed") {
			LogErr "Test failed. Last known status : $currentStatus."
			$testResult = "FAIL"
		}
		elseif ($finalStatus -imatch "TestAborted") {
			LogErr "Test Aborted. Last known status : $currentStatus."
			$testResult = "ABORTED"
		}
		elseif ($finalStatus -imatch "TestCompleted") {
			LogMsg "Test Completed."
			$testResult = "PASS"
		}
		elseif ($finalStatus -imatch "TestRunning") {
			LogMsg "Powershell backgroud job for test is completed but VM is reporting that test is still running. Please check $LogDir\zkConsoleLogs.txt"
			LogMsg "Contests of summary.log : $testSummary"
			$testResult = "PASS"
		}
		LogMsg "Test result : $testResult"
		LogMsg "Test Completed"

		LogMsg $currentTestResult.TestSummary
		if (!$uploadResults) {
			LogMsg "Zero throughput for some connections, results will not be uploaded to database!"
		}
		else {
			Send-ResultToDatabase -xmlConfig $xmlConfig -logDir $LogDir
		}
	} catch {
		$ErrorMessage =  $_.Exception.Message
		$ErrorLine = $_.InvocationInfo.ScriptLineNumber
		LogMsg "EXCEPTION : $ErrorMessage at line: $ErrorLine"
	} finally {
		if (!$testResult) {
			$testResult = "Aborted"
		}
		$resultArr += $testResult
	}

	$currentTestResult.TestResult = GetFinalResultHeader -resultarr $resultArr
	return $currentTestResult.TestResult
}

Main