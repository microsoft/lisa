# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
param([object] $AllVmData, [object] $CurrentTestData)

$testScript = "nested_kvm_storage_perf.sh"

function New-ShellScriptFiles($LogDir) {
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

function Start-TestExecution ($ip, $port) {
	Copy-RemoteFiles -uploadTo $ip -port $port -files $currentTestData.files -username $user -password $password -upload

	Run-LinuxCmd -username $user -password $password -ip $ip -port $port -command "chmod +x *" -runAsSudo

	Write-LogInfo "Executing : ${testScript}"
	$cmd = "/home/$user/${testScript} > /home/$user/TestExecutionConsole.log"
	$testJob = Run-LinuxCmd -username $user -password $password -ip $ip -port $port -command $cmd -runAsSudo -RunInBackground

	while ((Get-Job -Id $testJob).State -eq "Running") {
		$currentStatus = Run-LinuxCmd -username $user -password $password -ip $ip -port $port -command "cat /home/$user/state.txt"
		Write-LogInfo "Current Test Status : $currentStatus"
		Wait-Time -seconds 20
	}
}

function Send-ResultToDatabase ($currentTestResult, $AllVMData) {
	$fioDataCsv = Import-Csv -Path $LogDir\fioData.csv

	if ($TestPlatform -eq "hyperV") {
		$HostBy = $TestLocation
		$HyperVMappedSizes = [xml](Get-Content .\XML\AzureVMSizeToHyperVMapping.xml)
		$L1GuestCpuNum = $HyperVMappedSizes.HyperV.$HyperVInstanceSize.NumberOfCores
		$L1GuestMemMB = [int]($HyperVMappedSizes.HyperV.$HyperVInstanceSize.MemoryInMB)
		$L1GuestSize = "$($L1GuestCpuNum)Cores $($L1GuestMemMB/1024)G"
		$vm = Get-VM -Name $AllVMData.RoleName -ComputerName $AllVMData.HyperVHost
		$vhd = Get-VHD -Path $vm.HardDrives[1].Path
		$count = $vm.HardDrives.count - 1
		$disk_size = $vhd.PhysicalSectorSize
	} else {
		$HostBy	= ($global:TestLocation).Replace('"','')
		$L1GuestSize = $AllVMData.InstanceSize
		$vm = (Get-AzureRmVM -ResourceGroupName $AllVMData.ResourceGroupName -Name $AllVMData.RoleName)
		$count = $vm.StorageProfile.DataDisks.Count
		$disk_size = $vm.StorageProfile.DataDisks[0].DiskSizeGB
	}

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

	$TestDate = $(Get-Date -Format yyyy-MM-dd)
	Write-LogInfo "Generating the performance data for database insertion"

	for ( $QDepth = $startThread; $QDepth -le $maxThread; $QDepth *= 2 ) {
		if ($testResult -imatch $resultPass) {
			$resultMap = @{}
			$resultMap["TestCaseName"] = $GlobalConfig.Global.$TestPlatform.ResultsDatabase.testTag
			$resultMap["TestDate"] = $TestDate
			$resultMap["HostType"] = $TestPlatform
			$resultMap["HostBy"] = $HostBy
			$resultMap["HostOS"] = cat "$LogDir\VM_properties.csv" | Select-String "Host Version"| %{$_ -replace ",Host Version,",""}
			$resultMap["L1GuestOSType"] = "Linux"
			$resultMap["L1GuestDistro"] = cat "$LogDir\VM_properties.csv" | Select-String "OS type"| %{$_ -replace ",OS type,",""}
			$resultMap["L1GuestSize"] = $L1GuestSize
			$resultMap["L1GuestKernelVersion"] = cat "$LogDir\VM_properties.csv" | Select-String "Kernel version"| %{$_ -replace ",Kernel version,",""}
			$resultMap["L2GuestDistro"] = cat "$LogDir\nested_properties.csv" | Select-String "OS type"| %{$_ -replace ",OS type,",""}
			$resultMap["L2GuestKernelVersion"] = cat "$LogDir\nested_properties.csv" | Select-String "Kernel version"| %{$_ -replace ",Kernel version,",""}
			$resultMap["L2GuestCpuNum"] = $L2GuestCpuNum
			$resultMap["L2GuestMemMB"] = $L2GuestMemMB
			$resultMap["DiskSetup"] = "$count SSD: $($disk_size)G"
			$resultMap["RaidOption"] = $RaidOption
			$resultMap["BlockSize_KB"] = [Int]((($fioDataCsv |  where { $_.Threads -eq "$QDepth"} | Select BlockSize)[0].BlockSize).Replace("K",""))
			$resultMap["QDepth"] = $QDepth
			$resultMap["seq_read_iops"] = [Float](($fioDataCsv |  where { $_.TestType -eq "read" -and  $_.Threads -eq "$QDepth"} | Select ReadIOPS).ReadIOPS)
			$resultMap["seq_read_lat_usec"] = [Float](($fioDataCsv |  where { $_.TestType -eq "read" -and  $_.Threads -eq "$QDepth"} | Select MaxOfReadMeanLatency).MaxOfReadMeanLatency)
			$resultMap["rand_read_iops"] = [Float](($fioDataCsv |  where { $_.TestType -eq "randread" -and  $_.Threads -eq "$QDepth"} | Select ReadIOPS).ReadIOPS)
			$resultMap["rand_read_lat_usec"] = [Float](($fioDataCsv |  where { $_.TestType -eq "randread" -and  $_.Threads -eq "$QDepth"} | Select MaxOfReadMeanLatency).MaxOfReadMeanLatency)
			$resultMap["seq_write_iops"] = [Float](($fioDataCsv |  where { $_.TestType -eq "write" -and  $_.Threads -eq "$QDepth"} | Select WriteIOPS).WriteIOPS)
			$resultMap["seq_write_lat_usec"] = [Float](($fioDataCsv |  where { $_.TestType -eq "write" -and  $_.Threads -eq "$QDepth"} | Select MaxOfWriteMeanLatency).MaxOfWriteMeanLatency)
			$resultMap["rand_write_iops"] = [Float](($fioDataCsv |  where { $_.TestType -eq "randwrite" -and  $_.Threads -eq "$QDepth"} | Select WriteIOPS).WriteIOPS)
			$resultMap["rand_write_lat_usec"] = [Float](($fioDataCsv |  where { $_.TestType -eq "randwrite" -and  $_.Threads -eq "$QDepth"} | Select MaxOfWriteMeanLatency).MaxOfWriteMeanLatency)
			$currentTestResult.TestResultData += $resultMap
		}
		Write-LogInfo "Collected performance data for $QDepth QDepth."
	}
	Write-LogInfo ($fioDataCsv | Format-Table | Out-String)
}

function Main() {
	$currentTestResult = Create-TestResultObject
	$resultArr = @()
	$testResult = $resultAborted
	try {
		$hs1VIP = $AllVMData.PublicIP
		$hs1vm1sshport = $AllVMData.SSHPort

		New-ShellScriptFiles -logDir $LogDir
		Copy-RemoteFiles -uploadTo $hs1VIP -port $hs1vm1sshport -files "$LogDir\StartFioTest.sh,$LogDir\ParseFioTestLogs.sh" -username $user -password $password -upload

		Start-TestExecution -ip $hs1VIP -port $hs1vm1sshport

		$files="/home/$user/state.txt, /home/$user/$testScript.log, /home/$user/TestExecutionConsole.log"
		Copy-RemoteFiles -download -downloadFrom $hs1VIP -files $files -downloadTo $LogDir -port $hs1vm1sshport -username $user -password $password
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
		Copy-RemoteFiles -download -downloadFrom $hs1VIP -files "fioConsoleLogs.txt" -downloadTo $LogDir -port $hs1vm1sshport -username $user -password $password
		if ($testResult -imatch $resultPass) {
			Remove-Item "$LogDir\*.csv" -Force
			$remoteFiles = "FIOTest-*.tar.gz,perf_fio.csv,nested_properties.csv,VM_properties.csv,runlog.txt"
			Copy-RemoteFiles -download -downloadFrom $hs1VIP -files $remoteFiles -downloadTo $LogDir -port $hs1vm1sshport -username $user -password $password
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
			Send-ResultToDatabase -currentTestResult $currentTestResult -AllVMData $AllVMData
		}
	} catch {
		$errorMessage =  $_.Exception.Message
		$ErrorLine = $_.InvocationInfo.ScriptLineNumber
		Write-LogInfo "EXCEPTION : $errorMessage at line: $ErrorLine"
	}

	$resultArr += $testResult
	Write-LogInfo "Test result : $testResult"
	$currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
	return $currentTestResult
}


# Main Body
Main
