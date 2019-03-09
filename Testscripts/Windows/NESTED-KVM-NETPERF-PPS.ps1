# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
param([object] $AllVmData, [object] $CurrentTestData)

$testScript = "nested_kvm_netperf_pps.sh"

if(($($currentTestData.TestName)).Contains("AZURE-NESTED-KVM-NETPERF-PPS")) {
	$testScript = "nested_kvm_netperf_pps_nat.sh"
}

function Start-TestExecution ($ip, $port, $cmd) {
	Write-LogInfo "Executing : ${cmd}"
	$testJob = Run-LinuxCmd -username $user -password $password -ip $ip -port $port -command $cmd -runAsSudo -RunInBackground
	while ((Get-Job -Id $testJob).State -eq "Running" ) {
		$currentStatus = Run-LinuxCmd -username $user -password $password -ip $ip -port $port -command "cat /home/$user/state.txt"
		Write-LogInfo "Current Test Staus : $currentStatus"
		Wait-Time -seconds 20
	}
}

function Send-ResultToDatabase ($GlobalConfig, $logDir, $ParseResultArray) {
	Write-LogInfo "Uploading the test results.."
	$dataSource = $GlobalConfig.Global.$TestPlatform.ResultsDatabase.server
	$user = $GlobalConfig.Global.$TestPlatform.ResultsDatabase.user
	$password = $GlobalConfig.Global.$TestPlatform.ResultsDatabase.password
	$database = $GlobalConfig.Global.$TestPlatform.ResultsDatabase.dbname
	$dataTableName = $GlobalConfig.Global.$TestPlatform.ResultsDatabase.dbtable
	$TestCaseName = $GlobalConfig.Global.$TestPlatform.ResultsDatabase.testTag
	if ($dataSource -And $user -And $password -And $database -And $dataTableName) {
		# Get host info
		$HostType = $global:TestPlatform
		$HostBy = $TestLocation
		$HostOS = Get-Content "$LogDir\VM_properties.csv" | Select-String "Host Version"| Foreach-Object{$_ -replace ",Host Version,",""}

		# Get L1 guest info
		$L1GuestDistro = Get-Content "$LogDir\VM_properties.csv" | Select-String "OS type"| Foreach-Object{$_ -replace ",OS type,",""}
		$L1GuestOSType = "Linux"
		$L1GuestKernelVersion = Get-Content "$LogDir\VM_properties.csv" | Select-String "Kernel version"| Foreach-Object{$_ -replace ",Kernel version,",""}

		if ($TestPlatform -eq "hyperV") {
			$HyperVMappedSizes = [xml](Get-Content .\XML\AzureVMSizeToHyperVMapping.xml)
			$L1GuestCpuNum = $HyperVMappedSizes.HyperV.$HyperVInstanceSize.NumberOfCores
			$L1GuestMemMB = $HyperVMappedSizes.HyperV.$HyperVInstanceSize.MemoryInMB
			$L1GuestSize = $L1GuestCpuNum.ToString() +"Cores "+($L1GuestMemMB/1024).ToString()+"G"
		} else {
			$L1GuestSize = $AllVMData.InstanceSize
		}
		# Get L2 guest info
		$L2GuestDistro = Get-Content "$LogDir\nested_properties.csv" | Select-String "OS type"| Foreach-Object{$_ -replace ",OS type,",""}
		$L2GuestKernelVersion = Get-Content "$LogDir\nested_properties.csv" | Select-String "Kernel version"| Foreach-Object{$_ -replace ",Kernel version,",""}
		$flag=1
		if($TestLocation.split(',').Length -eq 2) {
			$flag=0
		}

		$imageName = $global:ARMImageName

		foreach ( $param in $currentTestData.TestParameters.param) {
			if ($param -match "NestedCpuNum") {
				$L2GuestCpuNum = [int]($param.split("=")[1])
			}
			if ($param -match "NestedMemMB") {
				$L2GuestMemMB = [int]($param.split("=")[1])
			}
			if ($param -match "NestedNetDevice") {
				$KvmNetDevice = $param.split("=")[1]
			}
			if ($param -match "test_type") {
				$test_type = $param.split("=")[1]
				$test_type = $test_type.Split('"')[1]
			}
		}

		$IPVersion = "IPv4"
		$ProtocolType = "TCP"
		$connectionString = "Server=$dataSource;uid=$user; pwd=$password;Database=$database;Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
		$SQLQuery = "INSERT INTO $dataTableName (TestCaseName,TestDate,HostType,HostBy,HostOS,L1GuestOSType,L1GuestDistro,L1GuestSize,L1GuestKernelVersion,L2GuestDistro,L2GuestKernelVersion,L2GuestMemMB,L2GuestCpuNum,KvmNetDevice,IPVersion,ProtocolType,TestPlatform,DataPath,SameHost,TestType,RxPpsMinimum,RxPpsMaximum,RxPpsAverage,TxPpsMinimum,TxPpsMaximum,TxPpsAverage,RxTxPpsMinimum,RxTxPpsMaximum,RxTxPpsAverage, ImageName) VALUES "
		$SQLQuery += "('$TestCaseName','$(Get-Date -Format yyyy-MM-dd)','$HostType','$HostBy','$HostOS','$L1GuestOSType','$L1GuestDistro','$L1GuestSize','$L1GuestKernelVersion','$L2GuestDistro','$L2GuestKernelVersion','$L2GuestMemMB','$L2GuestCpuNum','$KvmNetDevice','$IPVersion','$ProtocolType','$HostType','Synthetic','$flag','$test_type',$($ParseResultArray[0]),$($ParseResultArray[1]),$($ParseResultArray[2]),$($ParseResultArray[3]),$($ParseResultArray[4]),$($ParseResultArray[5]),$($ParseResultArray[6]),$($ParseResultArray[7]),$($ParseResultArray[8]),'$imageName')"
		Write-LogInfo $SQLQuery

		$connection = New-Object System.Data.SqlClient.SqlConnection
		$connection.ConnectionString = $connectionString
		$connection.Open()

		$command = $connection.CreateCommand()
		$command.CommandText = $SQLQuery
		$command.executenonquery()
		$connection.Close()
		Write-LogInfo "Uploading the test results done!!"
	} else {
		Write-LogInfo "Database details are not provided. Results will not be uploaded to database!"
	}
}

function Main () {
	$currentTestResult = Create-TestResultObject
	$resultArr = @()
	$testResult = $resultAborted
	try {
		foreach($vm in $AllVMData) {
			if($vm.RoleName.Contains("role-0") -or $vm.RoleName.Contains("receiver")) {
				$hs1VIP = $vm.PublicIP
				$hs1vm1sshport = $vm.SSHPort
				$hs1secondip = $vm.SecondInternalIP
			}
			if($vm.RoleName.Contains("role-1") -or $vm.RoleName.Contains("sender")) {
				$hs2VIP = $vm.PublicIP
				$hs2vm1sshport = $vm.SSHPort
				$hs2secondip = $vm.SecondInternalIP
			}
		}

		if($TestPlatform -eq "Azure") {
			$cmd = "/home/$user/${testScript} -role server -level1ClientIP $hs2secondip -level1ServerIP $hs1secondip -level1User $user -level1Password $password -level1Port 22 -logFolder /home/$user > /home/$user/TestExecutionConsole.log"
			Start-TestExecution -ip $hs1VIP -port $hs1vm1sshport -cmd $cmd

			$cmd = "/home/$user/${testScript} -role client -level1ClientIP $hs2secondip -level1ServerIP $hs1secondip -level1User $user -level1Password $password -level1Port 22 -logFolder /home/$user > /home/$user/TestExecutionConsole.log"
			Start-TestExecution -ip $hs2VIP -port $hs2vm1sshport -cmd $cmd
		} else {
			$cmd = "/home/$user/${testScript} -role server -level1ClientIP $hs2VIP -level1ClientUser $user -level1ClientPassword $password -level1ClientPort $hs2vm1sshport -logFolder /home/$user > /home/$user/TestExecutionConsole.log"
			Start-TestExecution -ip $hs1VIP -port $hs1vm1sshport -cmd $cmd

			$cmd = "/home/$user/${testScript} -role client -logFolder /home/$user > /home/$user/TestExecutionConsole.log"
			Start-TestExecution -ip $hs2VIP -port $hs2vm1sshport -cmd $cmd
		}

		# Download test logs
		Copy-RemoteFiles -download -downloadFrom $hs2VIP -files "/home/$user/state.txt, /home/$user/${testScript}.log, /home/$user/TestExecutionConsole.log" -downloadTo $LogDir -port $hs2vm1sshport -username $user -password $password

		$finalStatus = Get-Content $LogDir\state.txt
		if ($finalStatus -imatch "TestFailed") {
			Write-LogErr "Test failed. Last known status : $currentStatus."
			$testResult = $resultFail
		}
		elseif ($finalStatus -imatch "TestAborted") {
			Write-LogErr "Test Aborted. Last known status : $currentStatus."
			$testResult = $resultAborted
		}
		elseif ($finalStatus -imatch "TestCompleted") {
			$testResult = $resultPass
		}
		elseif ($finalStatus -imatch "TestRunning") {
			Write-LogInfo "Powershell background job for test is completed but VM is reporting that test is still running. Please check $LogDir\zkConsoleLogs.txt"
			$testResult = $resultAborted
		}
		if ($testResult -imatch $resultPass) {
			$nicName = "ens4"
			Copy-RemoteFiles -downloadFrom $hs2VIP -port $hs2vm1sshport -username $user -password $password -download -downloadTo $LogDir -files "netperfConsoleLogs.txt"
			Copy-RemoteFiles -downloadFrom $hs2VIP -port $hs2vm1sshport -username $user -password $password -download -downloadTo $LogDir -files "TestExecution.log"
			Copy-RemoteFiles -downloadFrom $hs2VIP -port $hs2vm1sshport -username $user -password $password -download -downloadTo $LogDir -files "netperf-client-sar-output.txt"
			Copy-RemoteFiles -downloadFrom $hs2VIP -port $hs2vm1sshport -username $user -password $password -download -downloadTo $LogDir -files "netperf-client-output.txt"
			Copy-RemoteFiles -downloadFrom $hs2VIP -port $hs2vm1sshport -username $user -password $password -download -downloadTo $LogDir -files "netperf-server-sar-output.txt"
			Copy-RemoteFiles -downloadFrom $hs2VIP -port $hs2vm1sshport -username $user -password $password -download -downloadTo $LogDir -files "netperf-server-output.txt"
			Copy-RemoteFiles -downloadFrom $hs2VIP -port $hs2vm1sshport -username $user -password $password -download -downloadTo $LogDir -files "VM_properties.csv"
			Copy-RemoteFiles -downloadFrom $hs2VIP -port $hs2vm1sshport -username $user -password $password -download -downloadTo $LogDir -files "nested_properties.csv"
			$NetperfReportLog = Get-Content -Path "$LogDir\netperf-client-sar-output.txt"
			if (!$NetperfReportLog) {
				$testResult = $resultFail
				throw "Invalid netperf report file"
			}
			$uploadResults = $true
			$checkValues = "$resultPass,$resultFail,$resultAborted"
			$ParseResultArray=@()
			#Region : parse the logs
			try {
				$RxPpsArray = @()
				$TxPpsArray = @()
				$TxRxTotalPpsArray = @()

				foreach ($line in $NetperfReportLog) {
					if ($line -imatch "$nicName" -and $line -inotmatch "Average") {
						Write-LogInfo "Collecting data from '$line'"
						$line = $line.Replace("  ", " ").Replace("  ", " ").Replace("  ", " ").Replace("  ", " ").Replace("  ", " ")
						for ($i = 0; $i -lt $line.split(' ').Count; $i++) {
							if ($line.split(" ")[$i] -eq "$nicName") {
								break;
							}
						}
						$RxPps = [int]$line.Replace("  ", " ").Replace("  ", " ").Replace("  ", " ").Replace("  ", " ").Split(" ")[$i+1]
						$RxPpsArray += $RxPps
						$TxPps = [int]$line.Replace("  ", " ").Replace("  ", " ").Replace("  ", " ").Replace("  ", " ").Split(" ")[$i+2]
						$TxPpsArray += $TxPps
						$TxRxTotalPpsArray += ($RxPps + $TxPps)
					}
				}
				$RxData = $RxPpsArray | Measure-Object -Maximum -Minimum -Average
				$RxPpsMinimum = $RxData.Minimum
				$RxPpsMaximum = $RxData.Maximum
				$RxPpsAverage = [math]::Round($RxData.Average,0)
				Write-LogInfo "RxPpsMinimum = $RxPpsMinimum"
				$ParseResultArray+=$RxPpsMinimum
				Write-LogInfo "RxPpsMaximum = $RxPpsMaximum"
				$ParseResultArray+=$RxPpsMaximum
				Write-LogInfo "RxPpsAverage = $RxPpsAverage"
				$ParseResultArray+=$RxPpsAverage

				$TxData = $TxPpsArray | Measure-Object -Maximum -Minimum -Average
				$TxPpsMinimum = $TxData.Minimum
				$TxPpsMaximum = $TxData.Maximum
				$TxPpsAverage = [math]::Round($TxData.Average,0)
				Write-LogInfo "TxPpsMinimum = $TxPpsMinimum"
				$ParseResultArray+=$TxPpsMinimum
				Write-LogInfo "TxPpsMaximum = $TxPpsMaximum"
				$ParseResultArray+=$TxPpsMaximum
				Write-LogInfo "TxPpsAverage = $TxPpsAverage"
				$ParseResultArray+=$TxPpsAverage

				$RxTxTotalData = $TxRxTotalPpsArray | Measure-Object -Maximum -Minimum -Average
				$RxTxPpsMinimum = $RxTxTotalData.Minimum
				$RxTxPpsMaximum = $RxTxTotalData.Maximum
				$RxTxPpsAverage = [math]::Round($RxTxTotalData.Average,0)
				Write-LogInfo "RxTxPpsMinimum = $RxTxPpsMinimum"
				$ParseResultArray+=$RxTxPpsMinimum
				Write-LogInfo "RxTxPpsMaximum = $RxTxPpsMaximum"
				$ParseResultArray+=$RxTxPpsMaximum
				Write-LogInfo "RxTxPpsAverage = $RxTxPpsAverage"
				$ParseResultArray+=$RxTxPpsMaximum

				$CurrentTestResult.TestSummary += New-ResultSummary -testResult "$RxPpsAverage" -metaData "Rx Average PPS" `
					-checkValues $checkValues -testName $currentTestData.testName
				$CurrentTestResult.TestSummary += New-ResultSummary -testResult "$RxPpsMinimum" -metaData "Rx Minimum PPS" `
					-checkValues $checkValues -testName $currentTestData.testName
				$CurrentTestResult.TestSummary += New-ResultSummary -testResult "$RxPpsMaximum" -metaData "Rx Maximum PPS" `
					-checkValues $checkValues -testName $currentTestData.testName
			} catch {
				$ErrorMessage = $_.Exception.Message
				$ErrorLine = $_.InvocationInfo.ScriptLineNumber
				Write-LogErr "EXCEPTION in Netperf log parsing : $ErrorMessage at line: $ErrorLine"
			}
			#endregion
		}

		Write-LogInfo $currentTestResult.TestSummary
		if (!$uploadResults) {
			Write-LogInfo "Zero throughput for some connections, results will not be uploaded to database!"
		} else {
			Send-ResultToDatabase -GlobalConfig $GlobalConfig -logDir $LogDir -ParseResultArray $ParseResultArray
		}
	} catch {
		$ErrorMessage =  $_.Exception.Message
		$ErrorLine = $_.InvocationInfo.ScriptLineNumber
		Write-LogInfo "EXCEPTION : $ErrorMessage at line: $ErrorLine"
	} finally {
		if (!$testResult) {
			$testResult = "Aborted"
		}
		$resultArr += $testResult
	}

	$currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
	return $currentTestResult.TestResult
}

Main
