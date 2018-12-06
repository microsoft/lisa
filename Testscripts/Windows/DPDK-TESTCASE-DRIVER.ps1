# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

# DPDK-TESTCASE-DRIVER.ps1 when used in conjunction with utils.sh, dpdkUtils.sh
# and dpdkSetupAndRunTest.sh provides a dpdk test environment.
#
# Testcases supply their own XML testcase, VM configuration (with one vm named
# "sender"), one powershell file, and one bash script file.
# The testcase provides 3 functions in its ps1 file:
#   1. Set-Test
#   2. Set-Runtime
#   3. Confirm-Performance
# The testcase provides 2 functions in its bash file:
#   1. Dpdk_Configure
#   2. Run_Testcase
#
# DPDK is automatically installed on all VMs and all their IPs are listed in the
# contants.sh file.

function Get-NonManagementNic() {
	param (
		[string] $vmName
	)

	$rg = $allVMData[0].ResourceGroupName
	$allNics = Get-AzureRmNetworkInterface -ResourceGroupName $rg | Where-Object {($null -ne $_.VirtualMachine.Id) `
		-and (($_.VirtualMachine.Id | Split-Path -leaf) -eq $vmName)}

	$nics = @()
	foreach ($nic in $allNics) {
		if ($nic.Primary -eq $false) {
			$nics += $nic
		}
	}

	Write-LogInfo "Found $($nics.count) non-management NIC(s)"
	return $nics
}

function Set-Phase() {
	[CmdletBinding(SupportsShouldProcess)]

	param (
		[string] $phase_msg
	)

	Set-Content "$LogDir\phase.txt" $phase_msg
	Write-LogInfo "Changing phase to $phase_msg"
	Run-LinuxCmd -ip $masterVM.PublicIP -port $masterVM.SSHPort -username $user -password $password -command "echo $phase_msg > phase.txt"
}

function Main {
	Write-LogInfo "DPDK-TESTCASE-DRIVER starting..."

	# Create test result
	$resultArr = @()

	try {
		# enables root access and key auth
		Provision-VMsForLisa -allVMData $allVMData -installPackagesOnRoleNames "none"

		Write-LogInfo "Generating constansts.sh ..."
		$constantsFile = "$LogDir\constants.sh"

		$ipAddrs = ""
		$vmNames = ""
		foreach ($vmData in $allVMData) {
			if ($vmData.RoleName -eq "sender") {
				$masterVM = $vmData
			}

			$roleName = $vmData.RoleName
			$internalIp = $vmData.InternalIP

			Write-LogInfo "VM $roleName details :"
			Write-LogInfo "  Public IP : $($vmData.PublicIP)"
			Write-LogInfo "  SSH Port : $($vmData.SSHPort)"
			Write-LogInfo "  Internal IP : $internalIp"
			Write-LogInfo ""

			$vmNames = "$vmNames $roleName"
			$ipAddrs = "$ipAddrs $internalIp"
			Add-Content -Value "$roleName=$internalIp" -Path $constantsFile

			# Validate if supported Distro and kernel version
			# https://docs.microsoft.com/en-us/azure/virtual-network/setup-dpdk
			$supportedDistro = "UBUNTU", "SLES", "SUSE", "REDHAT", "CENTOS"
			$UbuntuSupportKernelVersion = "4.15.0-1015-azure"
			$SLESSupportKernelVersion = "4.12.14-5.5-azure"
			$RHELSuppportKernelVersion = "3.10.0-862.9.1.el7"
			$CentOSSupportKernelVersion = "3.10.0-862.3.3.el7"

			$detectedDistro = Detect-LinuxDistro -VIP $vmData.PublicIP -SSHport $vmData.SSHPort `
					-testVMUser $user -testVMPassword $password

			if ( $supportedDistro.Contains($detectedDistro)) {
				Write-LogInfo "Confirmed Distro support: $detectedDistro"

				$currentKernelVersion = Run-LinuxCmd -ip $vmData.PublicIP -port $vmData.SSHPort `
					-username $user -password $password -command "uname -r"

				switch ( $detectedDistro ) {
					"UBUNTU" {
						if ($currentKernelVersion -ge $UbuntuSupportKernelVersion) {
							Write-LogInfo "Confirmed Kernel version supported: $currentKernelVersion"
						} else {
							Write-LogErr "Unsupported Kernel version: $currentKernelVersion"
							throw "Unsupported Kernel version: $currentKernelVersion"
						}
					}

					{($_ -eq "SLES") -or ($_ -eq "SUSE")} {
						if ($currentKernelVersion -ge $SLESSupportKernelVersion) {
							Write-LogInfo "Confirmed Kernel version supported: $currentKernelVersion"
						} else {
							Write-LogErr "Unsupported Kernel version: $currentKernelVersion"
							throw "Unsupported Kernel version: $currentKernelVersion"
						}
					}

					"REDHAT" {
						if ($currentKernelVersion -ge $RHELSuppportKernelVersion) {
							Write-LogInfo "Confirmed Kernel version supported: $currentKernelVersion"
						} else {
							Write-LogErr "Unsupported Kernel version: $currentKernelVersion"
							throw "Unsupported Kernel version: $currentKernelVersion"
						}
					}

					"CENTOS" {
						if ($currentKernelVersion -ge $CentOSSupportKernelVersion) {
							Write-LogInfo "Confirmed Kernel version supported: $currentKernelVersion"
						} else {
							Write-LogErr "Unsupported Kernel version: $currentKernelVersion"
							throw "Unsupported Kernel version: $currentKernelVersion"
						}
					}
				}

			} else {
				Write-LogErr "Unsupported Distro: $detectedDistro"
				throw "Unsupported Distro: $detectedDistro"
			}
		}

		if ($null -eq $masterVM) {
			throw "DPDK-TESTCASE-DRIVER requires at least one VM with RoleName of sender"
		}

		Add-Content -Value "VM_NAMES='$vmNames'" -Path $constantsFile
		Add-Content -Value "IP_ADDRS='$ipAddrs'" -Path $constantsFile
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
				# source user provided file for `Confirm-Performance`
				. $filePath
			} else {
				throw "user provided unsupported file type"
			}
		}
		# remove respective trailing delimiter
		$bashFilePaths = $bashFilePaths -replace ".$"
		$bashFileNames = $bashFileNames -replace ".$"

		Add-Content -Value "USER_FILES='$bashFileNames'" -Path $constantsFile

		Write-LogInfo "constanst.sh created successfully..."
		Write-LogInfo (Get-Content -Path $constantsFile)
		foreach ($param in $currentTestData.TestParameters.param) {
			Add-Content -Value "$param" -Path $constantsFile
		}

		Set-Test

		# start test
		$startTestCmd = @"
cd /root/
./dpdkSetupAndRunTest.sh 2>&1 > dpdkConsoleLogs.txt
. utils.sh
collect_VM_properties
"@
		Set-content "$LogDir\StartDpdkTest.sh" $startTestCmd
		# upload updated constants file to all VMs
		foreach ($vmData in $allVMData) {
			Copy-RemoteFiles -uploadTo $vmData.PublicIP -port $vmData.SSHPort -files "$constantsFile,.\Testscripts\Linux\utils.sh,.\Testscripts\Linux\dpdkUtils.sh," -username "root" -password $password -upload
		}
		Copy-RemoteFiles -uploadTo $masterVM.PublicIP -port $masterVM.SSHPort -files ".\Testscripts\Linux\dpdkSetupAndRunTest.sh,$LogDir\StartDpdkTest.sh" -username "root" -password $password -upload
		# upload user specified file from Testcase.xml to root's home
		Copy-RemoteFiles -uploadTo $masterVM.PublicIP -port $masterVM.SSHPort -files $bashFilePaths -username "root" -password $password -upload

		Run-LinuxCmd -ip $masterVM.PublicIP -port $masterVM.SSHPort -username "root" -password $password -command "chmod +x *.sh"
		$testJob = Run-LinuxCmd -ip $masterVM.PublicIP -port $masterVM.SSHPort -username "root" -password $password -command "./StartDpdkTest.sh" -RunInBackground

		# monitor test
		$outputCounter = 0
		$oldPhase = ""
		while ((Get-Job -Id $testJob).State -eq "Running") {
			if ($outputCounter -eq 5) {
				$currentOutput = Run-LinuxCmd -ip $masterVM.PublicIP -port $masterVM.SSHPort -username "root" -password $password -command "tail -2 dpdkConsoleLogs.txt | head -1"
				Write-LogInfo "Current Test Output: $currentOutput"

				$outputCounter = 0
			}

			$currentPhase = Run-LinuxCmd -ip $masterVM.PublicIP -port $masterVM.SSHPort -username "root" -password $password -command "cat phase.txt"
			if ($currentPhase -ne $oldPhase) {
				Write-LogInfo "Read new phase: $currentPhase"
				$oldPhase = $currentPhase
			}
			Set-Runtime

			++$outputCounter
			Wait-Time -seconds 5
		}
		$finalState = Run-LinuxCmd -ip $masterVM.PublicIP -port $masterVM.SSHPort -username "root" -password $password -command "cat /root/state.txt"
		Copy-RemoteFiles -downloadFrom $masterVM.PublicIP -port $masterVM.SSHPort -username "root" -password $password -download -downloadTo $LogDir -files "*.csv, *.txt, *.log"

		$testDataCsv = Import-Csv -Path $LogDir\dpdk_test.csv
		if ($finalState -imatch "TestFailed") {
			Write-LogErr "Test failed. Last known output: $currentOutput."
			$testResult = "FAIL"
		}
		elseif ($finalState -imatch "TestAborted") {
			Write-LogErr "Test Aborted. Last known output: $currentOutput."
			$testResult = "ABORTED"
		}
		elseif ($finalState -imatch "TestCompleted") {
			Write-LogInfo "Test Completed."
			Copy-RemoteFiles -downloadFrom $masterVM.PublicIP -port $masterVM.SSHPort -username "root" -password $password -download -downloadTo $LogDir -files "*.tar.gz"
			$testResult = (Confirm-Performance)
		}
		elseif ($finalState -imatch "TestRunning") {
			Write-LogWarn "Powershell backgroud job for test is completed but VM is reporting that test is still running. Please check $LogDir\zkConsoleLogs.txt"
			Write-LogWarn "Contests of summary.log : $testSummary"
			$testResult = "ABORTED"
		}

		Write-LogInfo "Test result : $testResult"
		try {
			Write-LogInfo "Uploading the test results.."
			$dataSource = $xmlConfig.config.Azure.database.server
			$DBuser = $xmlConfig.config.Azure.database.user
			$DBpassword = $xmlConfig.config.Azure.database.password
			$database = $xmlConfig.config.Azure.database.dbname
			$dataTableName = $xmlConfig.config.Azure.database.dbtable
			$TestCaseName = $xmlConfig.config.Azure.database.testTag

			if ($dataSource -And $DBuser -And $DBpassword -And $database -And $dataTableName) {
				$GuestDistro = Get-Content "$LogDir\VM_properties.csv" | Select-String "OS type"| ForEach-Object {$_ -replace ",OS type,",""}
				$HostType = "Azure"
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
				foreach ($mode in $testDataCsv) {
					$SQLQuery += "('$TestPlatform','$TestCaseName','$(Get-Date -Format yyyy-MM-dd)','$HostType','$HostBy','$HostOS','$GuestOSType','$GuestDistro','$GuestSize','$KernelVersion','Inbuilt','$IPVersion','$ProtocolType','$DataPath','$($mode.dpdk_version)','$($mode.test_mode)','$($mode.core)','$($mode.max_rx_pps)','$($mode.tx_pps_avg)','$($mode.rx_pps_avg)','$($mode.fwdtx_pps_avg)','$($mode.tx_bytes)','$($mode.rx_bytes)','$($mode.fwd_bytes)','$($mode.tx_packets)','$($mode.rx_packets)','$($mode.fwd_packets)','$($mode.tx_packet_size)','$($mode.rx_packet_size)'),"
					Write-LogInfo "Collected performace data for $($mode.TestMode) mode."
				}
				$SQLQuery = $SQLQuery.TrimEnd(',')
				Write-LogInfo $SQLQuery
				$connection = New-Object System.Data.SqlClient.SqlConnection
				$connection.ConnectionString = $connectionString
				$connection.Open()

				$command = $connection.CreateCommand()
				$command.CommandText = $SQLQuery

				$command.executenonquery() | Out-Null
				$connection.Close()
				Write-LogInfo "Uploading the test results done!!"
			} else {
				Write-LogErr "Invalid database details. Failed to upload result to database!"
				$ErrorMessage =  $_.Exception.Message
				$ErrorLine = $_.InvocationInfo.ScriptLineNumber
				Write-LogErr "EXCEPTION : $ErrorMessage at line: $ErrorLine"
			}
		} catch {
			$ErrorMessage =  $_.Exception.Message
			throw "$ErrorMessage"
			$testResult = "FAIL"
		}
		Write-LogInfo "Test result : $testResult"
		Write-LogInfo ($testDataCsv | Format-Table | Out-String)
	}
	catch {
		$ErrorMessage =  $_.Exception.Message
		$ErrorLine = $_.InvocationInfo.ScriptLineNumber
		Write-LogErr "EXCEPTION : $ErrorMessage at line: $ErrorLine"
	} finally {
		if (!$testResult) {
			$testResult = "Aborted"
		}
		$resultArr += $testResult
		$currentTestResult.TestSummary +=  Create-ResultSummary -testResult $testResult -metaData "DPDK-TEST" -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
	}

	$currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
	return $currentTestResult.TestResult
}

Main
