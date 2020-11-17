# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
param(
	[String] $TestParams,
	[object] $AllVMData,
	[object] $CurrentTestData
)

function Main {
	param (
		$TestParams
	)
	$currentTestResult = Create-TestResultObject
	$scriptFile = "./ntttcp_monitor_throughput.sh"
	$log_dir = "/var/log/ntttcp_monitor"

	$serverVMData = $allVMData | Select-Object -First 1
	$server_internal_ip = $serverVMData.InternalIP
	$serverResult = Run-LinuxCmd -ip $serverVMData.PublicIP -port $serverVMData.SSHPort -username $global:user `
		-password $password -command "chmod +x *.sh && $scriptFile --log_dir '${log_dir}' --server_internal_ip '${server_internal_ip}'" -runAsSudo -ignoreLinuxExitCode
	if ($serverResult -cmatch "Ntttcp_Monitor_Server_Started") {
		$serverStartedSuccessfully = $true
	}

	if (!$serverStartedSuccessfully) {
		Write-LogErr "Failed to start NTTTCP server"
		$currentTestResult.TestResult = $global:ResultFail
	}
	else {
		$clientVMData = $allVMData | Where-Object {$_.InternalIP -inotmatch "$server_internal_ip"} | Select-Object -First 1
		$null = Run-LinuxCmd -ip $clientVMData.PublicIP -port $clientVMData.SSHPort -username $global:user `
				-password $global:password -command "rm -f state.txt && chmod +x *.sh && (nohup '${scriptFile}' --log_dir '${log_dir}' --server_internal_ip '${server_internal_ip}' & ); sleep 30" -runAsSudo -ignoreLinuxExitCode
		$timeout = New-TimeSpan -Seconds 300
		$sw = [System.Diagnostics.Stopwatch]::StartNew()
		while ($clientNtttcpStatus -inotmatch "^TestRunning.*" -and $sw.Elapsed -lt $timeout) {
			Start-Sleep -Seconds 5
			$clientNtttcpStatus = Run-LinuxCmd -ip $clientVMData.PublicIP -port $clientVMData.SSHPort -username $global:user `
				-password $password -command "cat ${log_dir}/state.txt" -runAsSudo -ignoreLinuxExitCode
		}
		if ($clientNtttcpStatus -imatch "^TestRunning.*") {
			$currentTestResult.TestResult = $global:ResultPass
			$connectionInfo = "Client Address: $($clientVMData.PublicIP):$($clientVMData.SSHPort), Server Address: $($serverVMData.PublicIP):$($serverVMData.SSHPort)"
			$currentTestResult.TestSummary += New-ResultSummary -testResult $connectionInfo -metaData "Monitor NTTTCP Started Successfully" -testName $CurrentTestData.TestName
			$currentTestResult.TestSummary += New-ResultSummary -testResult $clientNtttcpStatus -metaData "State" -testName $CurrentTestData.TestName
			Write-LogInfo "Adding resource group tag: NTTTCP_MONITOR_THROUGHPUT=yes Started_Time=$(Get-Date)"
			$resourceGroupName = $clientVMData.ResourceGroupName
			if ($resourceGroupName) {
				Add-ResourceGroupTag -ResourceGroup $resourceGroupName -TagName "NTTTCP_MONITOR_THROUGHPUT" -TagValue "yes" | Out-Null
				Add-ResourceGroupTag -ResourceGroup $resourceGroupName -TagName "Started_Time" -TagValue "$(Get-Date)" | Out-Null
				Write-LogInfo "Adding Timer Lock on the resource group $resourceGroupName"
				New-AzResourceLock -LockName "Timer Lock" -LockLevel CanNotDelete -ResourceGroupName $resourceGroupName -Force | Out-Null
			}
		}
		else {
			Write-LogErr "Failed to start NTTTCP client"
			$currentTestResult.TestResult = $global:ResultFail
		}
	}
	return $currentTestResult
}

Main -TestParams (ConvertFrom-StringData $TestParams.Replace(";","`n"))