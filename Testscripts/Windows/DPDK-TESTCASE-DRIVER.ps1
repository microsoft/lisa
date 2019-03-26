# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

# DPDK-TESTCASE-DRIVER.ps1 when used in conjunction with utils.sh, dpdkUtils.sh
# and dpdkSetupAndRunTest.sh provides a dpdk test environment.
#
# Testcases supply their own XML testcase, VM configuration (with one vm named
# "sender"), one powershell file, and one bash script file.
# The testcase may provide 3 functions in its ps1 file (none are required):
#   1. Set-Test
#		To change any state before the test begins. For example, enable
#		IP forwarding on a VM's NIC. Get-NonManagementNic function is provided,
#		see this file for other variables that are available.
#   2. Set-Runtime
#		To change any state during the test's runtime. Same functions and
#		variables available to Set-Test are available for Set-Runtime plus one
#		more: "currentPhase". When the bash script side uses "Update_Phase" the
#		Set-Runtime function can get that phase by reading "currentPhase". This
#		allows both sides of the test to syncrhonize.
#   3. Confirm-Performance
#		To parse and finalize and data collected during the test run.
#
# The testcase provides 2 functions in its bash file:
#   1. Dpdk_Configure
#		To do any auxiliary configuration on DPDK before compilation. For
#		example, change testpmd ip's.
#   2. Run_Testcase	(required)
#		The function that the DPDK framework calls to actually run the testcase.
#		Many functions and variables are provided to both Dpdk_Configure and
#		Run_Testcase. Please see dpdkUtils.sh for more information.
#
# DPDK is automatically installed on all VMs and all their IPs are listed in the
# contants.sh file.

param([object] $CurrentTestData,
      [object] $AllVmData)

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

function Get-FunctionAndWarn() {
	param (
		[string] $funcName
	)

	if (Get-Command $funcName -ErrorAction SilentlyContinue) {
		return $true
	} else {
		Write-LogWarn "Testcase did not provide $funcName. If function is not necessary this warning may be ignored."
		return $false
	}
}

function Get-FunctionAndInvoke() {
	param (
		[string] $funcName
	)

	if (Get-Command $funcName -ErrorAction SilentlyContinue) {
		return & $funcName
	}
}

function Set-Phase() {
	[CmdletBinding(SupportsShouldProcess)]

	param (
		[string] $phase_msg
	)
	$superUser = "root"

	Set-Content "$LogDir\phase.txt" $phase_msg
	Write-LogInfo "Changing phase to $phase_msg"
	Run-LinuxCmd -ip $masterVM.PublicIP -port $masterVM.SSHPort -username $superUser -password $password -command "echo $phase_msg > phase.txt"
}

function Confirm-WithinPercentage() {
	param (
		[double]$num0,
		[double]$num1,
		$percent = 20
	)

	$variation = ($num0 - $num1) / $num1 * 100
	if ($variation -gt 0) {
		Write-LogInfo "Positive variation ${variation} for the performance."
		return $true
	} else {
		$variation = [math]::abs($variation)
		if ($variation -gt $percent) {
			Write-LogErr "Negative variation ${variation} for the performance greater than the threshold ${percent}."
			return $false
		} else {
			Write-LogWarn "Negative variation ${variation} for the performance smaller than the threshold ${percent}."
			return $true
		}
	}
}

function Main {
	Write-LogInfo "DPDK-TESTCASE-DRIVER starting..."

	# Create test result
	$resultArr = @()
	$currentTestResult = Create-TestResultObject

	$superUser = "root"

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

			$detectedDistro = Detect-LinuxDistro -VIP $vmData.PublicIP -SSHport $vmData.SSHPort `
					-testVMUser $user -testVMPassword $password
			$currentKernelVersion = Run-LinuxCmd -ip $vmData.PublicIP -port $vmData.SSHPort `
					-username $user -password $password -command "uname -r"
			if (IsGreaterKernelVersion -actualKernelVersion $currentKernelVersion -detectedDistro $detectedDistro) {
					Write-LogInfo "Confirmed Kernel version supported: $currentKernelVersion"
			} else {
				Write-LogErr "Unsupported Kernel version: $currentKernelVersion"
				throw "Unsupported Kernel version: $currentKernelVersion"
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

		Write-LogInfo "constants.sh created successfully..."
		Write-LogInfo (Get-Content -Path $constantsFile)
		foreach ($param in $currentTestData.TestParameters.param) {
			Add-Content -Value "$param" -Path $constantsFile
		}

		$settestCMD = "Set-Test"
		if (Get-FunctionAndWarn($settestCMD)) {
			& $settestCMD
		}
		Get-FunctionAndWarn("Set-Runtime")
		Get-FunctionAndWarn("Confirm-Performance")

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
			Copy-RemoteFiles -uploadTo $vmData.PublicIP -port $vmData.SSHPort -files "$constantsFile,.\Testscripts\Linux\utils.sh,.\Testscripts\Linux\dpdkUtils.sh," -username $superUser -password $password -upload
		}
		Copy-RemoteFiles -uploadTo $masterVM.PublicIP -port $masterVM.SSHPort -files ".\Testscripts\Linux\dpdkSetupAndRunTest.sh,$LogDir\StartDpdkTest.sh" -username $superUser -password $password -upload
		# upload user specified file from Testcase.xml to root's home
		Copy-RemoteFiles -uploadTo $masterVM.PublicIP -port $masterVM.SSHPort -files $bashFilePaths -username $superUser -password $password -upload

		Run-LinuxCmd -ip $masterVM.PublicIP -port $masterVM.SSHPort -username $superUser -password $password -command "chmod +x *.sh"
		$testJob = Run-LinuxCmd -ip $masterVM.PublicIP -port $masterVM.SSHPort -username $superUser -password $password -command "./StartDpdkTest.sh" -RunInBackground

		# monitor test
		$outputCounter = 0
		$oldPhase = ""
		while ((Get-Job -Id $testJob).State -eq "Running") {
			if ($outputCounter -eq 5) {
				$currentOutput = Run-LinuxCmd -ip $masterVM.PublicIP -port $masterVM.SSHPort -username $superUser -password $password -command "tail -2 dpdkConsoleLogs.txt | head -1"
				Write-LogInfo "Current Test Output: $currentOutput"

				$outputCounter = 0
			}

			$currentPhase = Run-LinuxCmd -ip $masterVM.PublicIP -port $masterVM.SSHPort -username $superUser -password $password -command "cat phase.txt"
			if ($currentPhase -ne $oldPhase) {
				Write-LogInfo "Read new phase: $currentPhase"
				$oldPhase = $currentPhase
			}
			Get-FunctionAndInvoke("Set-Runtime")

			++$outputCounter
			Wait-Time -seconds 5
		}
		$finalState = Run-LinuxCmd -ip $masterVM.PublicIP -port $masterVM.SSHPort -username $superUser -password $password -command "cat /root/state.txt"
		Copy-RemoteFiles -downloadFrom $masterVM.PublicIP -port $masterVM.SSHPort -username $superUser -password $password -download -downloadTo $LogDir -files "*.csv, *.txt, *.log"

		$testDataCsv = Import-Csv -Path "${LogDir}\dpdk_test.csv"

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
			Copy-RemoteFiles -downloadFrom $masterVM.PublicIP -port $masterVM.SSHPort -username $superUser -password $password -download -downloadTo $LogDir -files "*.tar.gz"
			$testResult = "PASS"
			$testResult = (Get-FunctionAndInvoke("Confirm-Performance"))
		}
		elseif ($finalState -imatch "TestRunning") {
			Write-LogWarn "Powershell background job for test is completed but VM is reporting that test is still running. Please check $LogDir\zkConsoleLogs.txt"
			Write-LogWarn "Content of summary.log : $testSummary"
			$testResult = "ABORTED"
		}

		if ($testDataCsv -and @("PASS","FAIL").contains($testResult)) {
			Write-LogInfo "Parsing the performance data for database insertion"
			$properties = Get-VMProperties -PropertyFilePath "$LogDir\VM_properties.csv"
			$testDate = $(Get-Date -Format yyyy-MM-dd)
			foreach ($mode in $testDataCsv) {
				$resultMap = @{}
				if ($properties) {
					$resultMap["GuestDistro"] = $properties.GuestDistro
					$resultMap["HostOS"] = $properties.HostOS
					$resultMap["KernelVersion"] = $properties.KernelVersion
				}
				$resultMap["HostType"] = "Azure"
				$resultMap["HostBy"] = $global:TestLocation
				$resultMap["GuestOSType"] = "Linux"
				$resultMap["GuestSize"] = $masterVM.InstanceSize
				$resultMap["IPVersion"] = "IPv4"
				$resultMap["ProtocolType"] = "TCP"
				$resultMap["TestPlatFrom"] = $global:TestPlatForm
				$resultMap["TestCaseName"] = $global:GlobalConfig.Global.Azure.ResultsDatabase.testTag
				$resultMap["TestDate"] = $testDate
				$resultMap["LISVersion"] = "Inbuilt"
				if ($currentTestData.AdditionalHWConfig.Networking -imatch "SRIOV") {
					$resultMap["DataPath"] = "SRIOV"
				} else {
					$resultMap["DataPath"] = "Synthetic"
				}
				$resultMap["DPDKVersion"] = $mode.dpdk_version
				$resultMap["TestMode"] = $mode.test_mode
				$resultMap["Cores"] = [int32]($mode.core)
				$resultMap["Max_Rxpps"] = [int64]($mode.max_rx_pps)
				$resultMap["Txpps"] = [int64]($mode.tx_pps_avg)
				$resultMap["Rxpps"] = [int64]($mode.rx_pps_avg)
				$resultMap["Fwdpps"] = [int64]($mode.fwdtx_pps_avg)
				$resultMap["Txbytes"] = [int64]($mode.tx_bytes)
				$resultMap["Rxbytes"] = [int64]($mode.rx_bytes)
				$resultMap["Fwdbytes"] = [int64]($mode.fwd_bytes)
				$resultMap["Txpackets"] = [int64]($mode.tx_packets)
				$resultMap["Rxpackets"] = [int64]($mode.rx_packets)
				$resultMap["Fwdpackets"] = [int64]($mode.fwd_packets)
				$resultMap["Tx_PacketSize_KBytes"] = [Decimal]($mode.tx_packet_size)
				$resultMap["Rx_PacketSize_KBytes"] = [Decimal]($mode.rx_packet_size)
				Write-LogInfo "Collected performance data for $($mode.test_mode) mode."
				$currentTestResult.TestResultData += $resultMap
			}
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
		$currentTestResult.TestSummary +=  New-ResultSummary -testResult $testResult -metaData "DPDK-TEST" -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
	}

	$currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
	return $currentTestResult
}

Main
