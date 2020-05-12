# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
<#
.Synopsis
	CPU offline feature testing with vmbus interrupt channel reassignment

.Description
	CPU offline and verify no error in dmesg/syslog
	CPU offline all except one
#>

param([object] $AllVmData, [string]$TestParams)

function Main {
	param($AllVMData, $TestParams)
	$currentTestResult = Create-TestResultObject
	try {
		$testResult = $resultFail

		#region Generate constants.sh
		# We need to add extra parameters to constants.sh file apart from parameter properties defined in XML.
		# Hence, we are generating constants.sh file again in test script.

		Write-LogInfo "Generating constants.sh ..."
		$constantsFile = "$LogDir\constants.sh"
		foreach ($TestParam in $CurrentTestData.TestParameters.param) {
			Add-Content -Value "$TestParam" -Path $constantsFile
			Write-LogInfo "$TestParam added to constants.sh"
		}

		Write-LogInfo "constants.sh created successfully..."
		#endregion

		#region Upload files to master VM
		foreach ($VMData in $AllVMData) {
			Copy-RemoteFiles -uploadTo $VMData.PublicIP -port $VMData.SSHPort -files "$constantsFile,$($CurrentTestData.files)" -username $user -password $password -upload
			Write-LogInfo "Copied the script files to the VM"
		}
		#endregion

		# ##################################################################################
		# New kernel build for CPU channel change and vmbus interrupt re-assignment
		Run-LinuxCmd -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password -command "./CPUOfflineKernelBuild.sh" -RunInBackground -runAsSudo -ignoreLinuxExitCode:$true | Out-Null
		Write-LogInfo "Executing CPUOfflineKernelBuild script inside VM"

		# Wait for kernel compilation completion. 60 min timeout
		$timeout = New-Timespan -Minutes 60
		$sw = [diagnostics.stopwatch]::StartNew()
		while ($sw.elapsed -lt $timeout){
			$vmCount = $AllVMData.Count
			Wait-Time -seconds 15
			$state = Run-LinuxCmd -ip $VMData.PublicIP -port $VMData.SSHPort -username $user -password $password -command "cat ~/state.txt"
			if ($state -eq "TestCompleted") {
				$kernelCompileCompleted = Run-LinuxCmd -ip $VMData.PublicIP -port $VMData.SSHPort -username $user -password $password -command "cat ~/constants.sh | grep setup_completed=0" -runAsSudo
				if ($kernelCompileCompleted -ne "setup_completed=0") {
					Write-LogErr "CPUOfflineKernelBuild.sh finished on $($VMData.RoleName) but setup was not successful!"
				} else {
					Write-LogInfo "CPUOfflineKernelBuild.sh finished on $($VMData.RoleName)"
					$vmCount--
				}
				break
			} elseif ($state -eq "TestSkipped") {
				Write-LogInfo "CPUOfflineKernelBuild.sh finished with SKIPPED state!"
				$resultArr = $resultSkipped
				$currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
				return $currentTestResult.TestResult
			} elseif ($state -eq "TestFailed") {
				Write-LogErr "CPUOfflineKernelBuild.sh didn't finish successfully!"
				$resultArr = $resultFail
				$currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
				return $currentTestResult.TestResult
			} elseif ($state -eq "TestAborted") {
				Write-LogInfo "CPUOfflineKernelBuild.sh finished with Aborted state!"
				$resultArr = $resultAborted
				$currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
				return $currentTestResult.TestResult
			} else {
				Write-LogInfo "CPUOfflineKernelBuild.sh is still running in the VM!"
			}
		}
		if ($vmCount -le 0){
			Write-LogInfo "CPUOfflineKernelBuild.sh is done successfully"
		} else {
			Throw "CPUOfflineKernelBuild.sh didn't finish in the VM!"
		}

		# ##################################################################################
		# Reboot VM to apply RDMA changes
		Write-LogInfo "Rebooting VM!"
		$TestProvider.RestartAllDeployments($AllVMData)

		# ##################################################################################
		# Running CPU channel change
		Run-LinuxCmd -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password -command "./channel_change.sh" -RunInBackground -runAsSudo -ignoreLinuxExitCode:$true | Out-Null
		Write-LogInfo "Executed channel_change script inside VM"

		# Wait for kernel compilation completion. 60 min timeout
		$timeout = New-Timespan -Minutes 60
		$sw = [diagnostics.stopwatch]::StartNew()
		while ($sw.elapsed -lt $timeout){
			$vmCount = $AllVMData.Count
			Wait-Time -seconds 15
			$state = Run-LinuxCmd -ip $VMData.PublicIP -port $VMData.SSHPort -username $user -password $password -command "cat ~/state.txt"
			if ($state -eq "TestCompleted") {
				$kernelCompileCompleted = Run-LinuxCmd -ip $VMData.PublicIP -port $VMData.SSHPort -username $user -password $password -command "cat ~/constants.sh | grep job_completed=0" -runAsSudo
				if ($kernelCompileCompleted -ne "job_completed=0") {
					Write-LogErr "channel_change.sh finished on $($VMData.RoleName) but job was not successful!"
				} else {
					Write-LogInfo "channel_change.sh finished on $($VMData.RoleName)"
					$vmCount--
				}
				break
			} elseif ($state -eq "TestSkipped") {
				Write-LogInfo "channel_change.sh finished with SKIPPED state!"
				$resultArr = $resultSkipped
				$currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
				return $currentTestResult.TestResult
			} elseif ($state -eq "TestFailed") {
				Write-LogErr "channel_change.sh didn't finish successfully!"
				$resultArr = $resultFail
				$currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
				return $currentTestResult.TestResult
			} elseif ($state -eq "TestAborted") {
				Write-LogInfo "channel_change.sh finished with Aborted state!"
				$resultArr = $resultAborted
				$currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
				return $currentTestResult.TestResult
			} else {
				Write-LogInfo "channel_change.sh is still running in the VM!"
			}
		}
		if ($vmCount -le 0){
			Write-LogInfo "channel_change.sh is done"
		} else {
			Throw "channel_change.sh didn't finish in the VM!"
		}

		$testResult = $resultPass
	} catch {
		$ErrorMessage =  $_.Exception.Message
		$ErrorLine = $_.InvocationInfo.ScriptLineNumber
		Write-LogErr "EXCEPTION : $ErrorMessage at line: $ErrorLine"
	} finally {
		if (!$testResult) {
			$testResult = $resultAborted
		}
		$resultArr = $testResult
	}

	$currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
	return $currentTestResult
}

Main -AllVmData $AllVmData -CurrentTestData $CurrentTestData