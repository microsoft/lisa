# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
param([object] $AllVmData, [object] $CurrentTestData)

$testScript = "nested_kvm_storage_perf.sh"

function New-ShellScriptFiles($LogDir)
{
	$scriptContent = @"
chmod +x nested_kvm_perf_fio.sh
./nested_kvm_perf_fio.sh &> fioConsoleLogs.txt
. utils.sh
collect_VM_properties nested_properties.csv
"@

	$scriptContent2 = @"
chmod +x *.sh
cp fio_jason_parser.sh gawk JSON.awk utils.sh /root/FIOLog/jsonLog/
cd /root/FIOLog/jsonLog/
./fio_jason_parser.sh
cp perf_fio.csv /root
chmod 666 /root/perf_fio.csv
"@
	Set-Content "$LogDir\StartFioTest.sh" $scriptContent
	Set-Content "$LogDir\ParseFioTestLogs.sh" $scriptContent2
}

function Start-TestExecution ($ip, $port)
{
	Copy-RemoteFiles -uploadTo $ip -port $port -files $currentTestData.files -username $user -password $password -upload

	Run-LinuxCmd -username $user -password $password -ip $ip -port $port -command "chmod +x *" -runAsSudo

	Write-LogInfo "Executing : ${testScript}"
	$cmd = "/home/$user/${testScript} > /home/$user/TestExecutionConsole.log"
	$testJob = Run-LinuxCmd -username $user -password $password -ip $ip -port $port -command $cmd -runAsSudo -RunInBackground

	while ((Get-Job -Id $testJob).State -eq "Running" )
	{
		$currentStatus = Run-LinuxCmd -username $user -password $password -ip $ip -port $port -command "cat /home/$user/state.txt"
		Write-LogInfo "Current Test Status : $currentStatus"
		Wait-Time -seconds 20
	}
}

function Send-ResultToDatabase ($GlobalConfig, $logDir)
{
	Write-LogInfo "Uploading the test results.."
	$dataSource = $GlobalConfig.Global.$TestPlatform.ResultsDatabase.server
	$DBuser = $GlobalConfig.Global.$TestPlatform.ResultsDatabase.user
	$DBpassword = $GlobalConfig.Global.$TestPlatform.ResultsDatabase.password
	$database = $GlobalConfig.Global.$TestPlatform.ResultsDatabase.dbname
	$dataTableName = $GlobalConfig.Global.$TestPlatform.ResultsDatabase.dbtable
	$TestCaseName = $GlobalConfig.Global.$TestPlatform.ResultsDatabase.testTag
	if ($dataSource -And $DBuser -And $DBpassword -And $database -And $dataTableName)
	{
		$fioDataCsv = Import-Csv -Path $LogDir\fioData.csv
		$HostType = $TestPlatform
		if ($TestPlatform -eq "hyperV")
		{
			$HostBy = $TestLocation
			$HyperVMappedSizes = [xml](Get-Content .\XML\AzureVMSizeToHyperVMapping.xml)
			$L1GuestCpuNum = $HyperVMappedSizes.HyperV.$HyperVInstanceSize.NumberOfCores
			$L1GuestMemMB = [int]($HyperVMappedSizes.HyperV.$HyperVInstanceSize.MemoryInMB)
			$L1GuestSize = "$($L1GuestCpuNum)Cores $($L1GuestMemMB/1024)G"
		}
		else
		{
			$HostBy	= ($global:TestLocation).Replace('"','')
			$L1GuestSize = $AllVMData.InstanceSize
		}
		$count = 0

		# TODO: Change to get the disk size from either host side or guest side
		<#
		foreach ($disk in $xmlConfig.config.$TestPlatform.Deployment.$setupType.ResourceGroup.VirtualMachine.DataDisk)
		{
			$disk_size = $disk.DiskSizeInGB
			$count ++
		} #>
		$DiskSetup = "$count SSD: $($disk_size)G"
		$HostOS = cat "$LogDir\VM_properties.csv" | Select-String "Host Version"| %{$_ -replace ",Host Version,",""}
		# Get L1 guest info
		$L1GuestDistro = cat "$LogDir\VM_properties.csv" | Select-String "OS type"| %{$_ -replace ",OS type,",""}
		$L1GuestOSType = "Linux"
		$L1GuestKernelVersion = cat "$LogDir\VM_properties.csv" | Select-String "Kernel version"| %{$_ -replace ",Kernel version,",""}

		# Get L2 guest info
		$L2GuestDistro = cat "$LogDir\nested_properties.csv" | Select-String "OS type"| %{$_ -replace ",OS type,",""}
		$L2GuestKernelVersion = cat "$LogDir\nested_properties.csv" | Select-String "Kernel version"| %{$_ -replace ",Kernel version,",""}
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
			$seq_read_iops = [Float](($fioDataCsv |  where { $_.TestType -eq "read" -and  $_.Threads -eq "$QDepth"} | Select ReadIOPS).ReadIOPS)
			$seq_read_lat_usec = [Float](($fioDataCsv |  where { $_.TestType -eq "read" -and  $_.Threads -eq "$QDepth"} | Select MaxOfReadMeanLatency).MaxOfReadMeanLatency)

			$rand_read_iops = [Float](($fioDataCsv |  where { $_.TestType -eq "randread" -and  $_.Threads -eq "$QDepth"} | Select ReadIOPS).ReadIOPS)
			$rand_read_lat_usec = [Float](($fioDataCsv |  where { $_.TestType -eq "randread" -and  $_.Threads -eq "$QDepth"} | Select MaxOfReadMeanLatency).MaxOfReadMeanLatency)

			$seq_write_iops = [Float](($fioDataCsv |  where { $_.TestType -eq "write" -and  $_.Threads -eq "$QDepth"} | Select WriteIOPS).WriteIOPS)
			$seq_write_lat_usec = [Float](($fioDataCsv |  where { $_.TestType -eq "write" -and  $_.Threads -eq "$QDepth"} | Select MaxOfWriteMeanLatency).MaxOfWriteMeanLatency)

			$rand_write_iops = [Float](($fioDataCsv |  where { $_.TestType -eq "randwrite" -and  $_.Threads -eq "$QDepth"} | Select WriteIOPS).WriteIOPS)
			$rand_write_lat_usec= [Float](($fioDataCsv |  where { $_.TestType -eq "randwrite" -and  $_.Threads -eq "$QDepth"} | Select MaxOfWriteMeanLatency).MaxOfWriteMeanLatency)

			$BlockSize_KB= [Int]((($fioDataCsv |  where { $_.Threads -eq "$QDepth"} | Select BlockSize)[0].BlockSize).Replace("K",""))

			$SQLQuery += "('$TestCaseName','$(Get-Date -Format yyyy-MM-dd)','$HostType','$HostBy','$HostOS','$L1GuestOSType','$L1GuestDistro','$L1GuestSize','$L1GuestKernelVersion','$L2GuestDistro','$L2GuestKernelVersion','$L2GuestCpuNum','$L2GuestMemMB','$DiskSetup','$RaidOption','$BlockSize_KB','$QDepth','$seq_read_iops','$seq_read_lat_usec','$rand_read_iops','$rand_read_lat_usec','$seq_write_iops','$seq_write_lat_usec','$rand_write_iops','$rand_write_lat_usec'),"
			Write-LogInfo "Collected performance data for $QDepth QDepth."
		}

		$SQLQuery = $SQLQuery.TrimEnd(',')
		Write-Host $SQLQuery
		$connection = New-Object System.Data.SqlClient.SqlConnection
		$connection.ConnectionString = $connectionString
		$connection.Open()

		$command = $connection.CreateCommand()
		$command.CommandText = $SQLQuery

		$null = $command.executenonquery()
		$connection.Close()
		Write-LogInfo "Uploading the test results done."
	}
	else
	{
		Write-LogInfo "Database details are not provided. Results will not be uploaded to database!!"
	}
}

function Main()
{
	$currentTestResult = Create-TestResultObject
	$resultArr = @()
	$testResult = $resultAborted
	try
	{
		$hs1VIP = $AllVMData.PublicIP
		$hs1vm1sshport = $AllVMData.SSHPort

		New-ShellScriptFiles -logDir $LogDir
		Copy-RemoteFiles -uploadTo $hs1VIP -port $hs1vm1sshport -files "$LogDir\StartFioTest.sh,$LogDir\ParseFioTestLogs.sh" -username $user -password $password -upload

		Start-TestExecution -ip $hs1VIP -port $hs1vm1sshport

		$files="/home/$user/state.txt, /home/$user/$testScript.log, /home/$user/TestExecutionConsole.log"
		Copy-RemoteFiles -download -downloadFrom $hs1VIP -files $files -downloadTo $LogDir -port $hs1vm1sshport -username $user -password $password
		$finalStatus = Get-Content $LogDir\state.txt
		if ( $finalStatus -imatch "TestFailed")
		{
			Write-LogErr "Test failed. Last known status : $currentStatus."
			$testResult = $resultFail
		}
		elseif ( $finalStatus -imatch "TestAborted")
		{
			Write-LogErr "Test Aborted. Last known status : $currentStatus."
			$testResult = $resultAborted
		}
		elseif ( $finalStatus -imatch "TestCompleted")
		{
			$testResult = $resultPass
		}
		elseif ( $finalStatus -imatch "TestRunning")
		{
			Write-LogInfo "Powershell background job for test is completed but VM is reporting that test is still running. Please check $LogDir\TestExecutionConsole.txt"
			$testResult = $resultAborted
		}
		Copy-RemoteFiles -download -downloadFrom $hs1VIP -files "fioConsoleLogs.txt" -downloadTo $LogDir -port $hs1vm1sshport -username $user -password $password
		$CurrentTestResult.TestSummary += New-ResultSummary -testResult $testResult -metaData "" -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
		if ($testResult -imatch $resultPass)
		{
			Remove-Item "$LogDir\*.csv" -Force
			$remoteFiles = "FIOTest-*.tar.gz,perf_fio.csv,nested_properties.csv,VM_properties.csv,runlog.txt"
			Copy-RemoteFiles -download -downloadFrom $hs1VIP -files $remoteFiles -downloadTo $LogDir -port $hs1vm1sshport -username $user -password $password
			$checkValues = "$resultPass,$resultFail,$resultAborted"
			$CurrentTestResult.TestSummary += New-ResultSummary -testResult $testResult -metaData "" -checkValues $checkValues -testName $currentTestData.testName
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
			Send-ResultToDatabase -GlobalConfig $GlobalConfig -logDir $LogDir
		}
	}
	catch
	{
		$errorMessage =  $_.Exception.Message
		$ErrorLine = $_.InvocationInfo.ScriptLineNumber
		Write-LogInfo "EXCEPTION : $errorMessage at line: $ErrorLine"
	}

	$resultArr += $testResult
	Write-LogInfo "Test result : $testResult"
	$currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
	return $currentTestResult.TestResult
}


# Main Body
Main
