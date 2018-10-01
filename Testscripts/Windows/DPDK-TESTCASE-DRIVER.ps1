# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

function Main {
	# Create test result
	$resultArr = @()

	try {
		if ($allVMData.Count -eq 0) {
			throw "DPDK-TESTCASE-DRIVER requires at least one VM"
		}
		$masterVM = $allVMData[0]

		# enables root access and key auth
		ProvisionVMsForLisa -allVMData $allVMData -installPackagesOnRoleNames "none"

		LogMsg "Generating constansts.sh ..."
		$constantsFile = "$LogDir\constants.sh"

		$ipAddrs = ""
		foreach ($vmData in $allVMData) {
			$roleName = $vmData.RoleName
			$internalIp = $vmData.InternalIP

			LogMsg "VM $roleName details :"
			LogMsg "  Public IP : $($vmData.PublicIP)"
			LogMsg "  SSH Port : $($vmData.SSHPort)"
			LogMsg "  Internal IP : $internalIp"

			$ipAddrs = "$ipAddrs $internalIp"
			Add-Contnet -Value "$roleName=$internalIp" -Path $constantsFile
		}

		# separate user provided files source ps1s now
		# add sh to constants.sh to be sourced on VM
		$bashFilePaths = ""
		$bashFileNames = ""
		foreach ($filePath in $currentTestData.files.Split(",")) {
			$fileExt = $filePath.Split(".")[$filePath.Split(".").count - 1]

			if ($fileExt -eq "sh") {
				$bashFilePaths = "$bashFilePaths$filePath,"
				$fileName = $filePath.Split("\")[$filePath.Split("\").count - 1]
				$bashFileNames = "$bashFileNames$fileName "
			} elseif ($fileExt -eq "ps1") {
				# source user provided file for `Verify-Performance`
				. $filePath
			} else {
				throw "user provided unsupported file type"
			}
		}
		# remove respective trailing delimiter
		$bashFilePaths = $bashFilePaths -replace ".$"
		$bashFileNames = $bashFileNames -replace ".$"

		Add-Content -Value "IP_ADDRS='$ipAddrs'" -Path $constantsFile
		Add-Content -Value "USER_FILES='$bashFileNames'" -Path $constantsFile

		LogMsg "constanst.sh created successfully..."
		LogMsg (Get-Content -Path $constantsFile)

		# start test
		$myString = @"
cd /root/
./dpdkSetupAndRunTest.sh 2>&1 > dpdkConsoleLogs.txt
. utils.sh
collect_VM_properties
"@
		Set-content "$LogDir\StartDpdkTestPmd.sh" $myString
		# upload updated constants file to all VMs
		foreach ($vmData in $allVMData) {
			RemoteCopy -uploadTo $vmData.PublicIP -port $vmData.SSHPort -files ".\$constantsFile" -username "root" -password $password -upload
		}
		RemoteCopy -uploadTo $masterVM.PublicIP -port $masterVM.SSHPort -files ".\$constantsFile,.\Testscripts\Linux\utils.sh,.\Testscripts\Linux\dpdkUtils.sh,.\Testscripts\Linux\dpdkSetupAndRunTest.sh,.\$LogDir\StartDpdkTestPmd.sh" -username "root" -password $password -upload
		# upload user specified file from Testcase.xml to root's home
		RemoteCopy -uploadTo $masterVM.PublicIP -port $masterVM.SSHPort -files $bashFilePaths -username "root" -password $password -upload

		RunLinuxCmd -ip $masterVM.PublicIP -port $masterVM.SSHPort -username "root" -password $password -command "chmod +x *.sh"
		$testJob = RunLinuxCmd -ip $masterVM.PublicIP -port $masterVM.SSHPort -username "root" -password $password -command "./StartDpdkTestPmd.sh" -RunInBackground

		# monitor test
		while ((Get-Job -Id $testJob).State -eq "Running") {
			$currentStatus = RunLinuxCmd -ip $masterVM.PublicIP -port $masterVM.SSHPort -username "root" -password $password -command "tail -2 dpdkConsoleLogs.txt | head -1"
			LogMsg "Current Test Status : $currentStatus"
			WaitFor -seconds 20
		}
		$finalStatus = RunLinuxCmd -ip $masterVM.PublicIP -port $masterVM.SSHPort -username "root" -password $password -command "cat /root/state.txt"
		RemoteCopy -downloadFrom $masterVM.PublicIP -port $masterVM.SSHPort -username "root" -password $password -download -downloadTo $LogDir -files "*.csv, *.txt, *.log"

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
			RemoteCopy -downloadFrom $masterVM.PublicIP -port $masterVM.SSHPort -username "root" -password $password -download -downloadTo $LogDir -files "*.tar.gz"
			$testResult = (Verify-Performance)
		}
		elseif ($finalStatus -imatch "TestRunning") {
			LogWarn "Powershell backgroud job for test is completed but VM is reporting that test is still running. Please check $LogDir\zkConsoleLogs.txt"
			LogWarn "Contests of summary.log : $testSummary"
			$testResult = "ABORTED"
		}

		LogMsg "Test result : $testResult"
		try {
            $testpmdDataCsv = Import-Csv -Path $LogDir\dpdk_testpmd.csv
            LogMsg "Uploading the test results.."
            $dataSource = $xmlConfig.config.Azure.database.server
            $DBuser = $xmlConfig.config.Azure.database.user
            $DBpassword = $xmlConfig.config.Azure.database.password
            $database = $xmlConfig.config.Azure.database.dbname
            $dataTableName = $xmlConfig.config.Azure.database.dbtable
            $TestCaseName = $xmlConfig.config.Azure.database.testTag
            
            if ($dataSource -And $DBuser -And $DBpassword -And $database -And $dataTableName) {
                $GuestDistro = Get-Content "$LogDir\VM_properties.csv" | Select-String "OS type"| ForEach-Object {$_ -replace ",OS type,",""}
                if ($UseAzureResourceManager) {
                    $HostType = "Azure-ARM"
                } else {
                    $HostType = "Azure"
                }
                
                $HostBy = ($xmlConfig.config.Azure.General.Location).Replace('"','')
                $HostOS = Get-Content "$LogDir\VM_properties.csv" | Select-String "Host Version"| ForEach-Object {$_ -replace ",Host Version,",""}
                $GuestOSType = "Linux"
                $GuestDistro = Get-Content "$LogDir\VM_properties.csv" | Select-String "OS type"| ForEach-Object {$_ -replace ",OS type,",""}
                $GuestSize = $masterVM.InstanceSize
                $KernelVersion = Get-Content "$LogDir\VM_properties.csv" | Select-String "Kernel version"| ForEach-Object {$_ -replace ",Kernel version,",""}
                $IPVersion = "IPv4"
                $ProtocolType = "TCP"
                $connectionString = "Server=$dataSource;uid=$DBuser; pwd=$DBpassword;Database=$database;Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"

                $SQLQuery = "INSERT INTO $dataTableName (TestPlatFrom,TestCaseName,TestDate,HostType,HostBy,HostOS,GuestOSType,GuestDistro,GuestSize,KernelVersion,LISVersion,IPVersion,ProtocolType,DataPath,DPDKVersion,TestMode,Cores,Max_Rxpps,Txpps,Rxpps,Fwdpps,Txbytes,Rxbytes,Fwdbytes,Txpackets,Rxpackets,Fwdpackets,Tx_PacketSize_KBytes,Rx_PacketSize_KBytes) VALUES "
                foreach ($mode in $testpmdDataCsv) {
					$SQLQuery += "('$TestPlatform','$TestCaseName','$(Get-Date -Format yyyy-MM-dd)','$HostType','$HostBy','$HostOS','$GuestOSType','$GuestDistro','$GuestSize','$KernelVersion','Inbuilt','$IPVersion','$ProtocolType','$DataPath','$($mode.dpdk_version)','$($mode.test_mode)','$($mode.core)','$($mode.max_rx_pps)','$($mode.tx_pps_avg)','$($mode.rx_pps_avg)','$($mode.fwdtx_pps_avg)','$($mode.tx_bytes)','$($mode.rx_bytes)','$($mode.fwd_bytes)','$($mode.tx_packets)','$($mode.rx_packets)','$($mode.fwd_packets)','$($mode.tx_packet_size)','$($mode.rx_packet_size)'),"
                    LogMsg "Collected performace data for $($mode.TestMode) mode."
                }
                $SQLQuery = $SQLQuery.TrimEnd(',')
                LogMsg $SQLQuery
                $connection = New-Object System.Data.SqlClient.SqlConnection
                $connection.ConnectionString = $connectionString
                $connection.Open()

                $command = $connection.CreateCommand()
                $command.CommandText = $SQLQuery
                
                $command.executenonquery() | Out-Null
                $connection.Close()
                LogMsg "Uploading the test results done!!"
            } else {
                LogErr "Invalid database details. Failed to upload result to database!"
                $ErrorMessage =  $_.Exception.Message
                $ErrorLine = $_.InvocationInfo.ScriptLineNumber
                LogErr "EXCEPTION : $ErrorMessage at line: $ErrorLine"
            }
        } catch {
            $ErrorMessage =  $_.Exception.Message
            throw "$ErrorMessage"
            $testResult = "FAIL"
        }
        LogMsg "Test result : $testResult"
        LogMsg ($testpmdDataCsv | Format-Table | Out-String)
	}
	catch {
		$ErrorMessage =  $_.Exception.Message
		$ErrorLine = $_.InvocationInfo.ScriptLineNumber
		LogErr "EXCEPTION : $ErrorMessage at line: $ErrorLine"
	} finally {
		if (!$testResult) {
			$testResult = "Aborted"
		}
		$resultArr += $testResult
		$currentTestResult.TestSummary +=  CreateResultSummary -testResult $testResult -metaData "DPDK-TESTPMD" -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
	}

	$currentTestResult.TestResult = GetFinalResultHeader -resultarr $resultArr
	return $currentTestResult.TestResult
}

Main