# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
<#
.Synopsis
	CPU offline-online stress testing with vmbus interrupt channel reassignment via VM reboot

.Description
	CPU offline and verify no error in dmesg/syslog.
	CPU offline all except one.
	Reboot VM and repeat above steps for a few times.
#>

param([object] $AllVmData, [string]$TestParams)
# Set default Iteration value of the Stress test
$max_stress_count = 10

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
			if ($TestParam -imatch "maxIteration") {
				# Overwrite new max Iteration of CPU offline and online stress test
				$max_stress_count = [int]($TestParam.Replace("maxIteration=", "").Trim('"'))
			}
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
				$resultArr = $resultSkipped
				throw "CPUOfflineKernelBuild.sh finished with SKIPPED state!"
			} elseif ($state -eq "TestFailed") {
				$resultArr = $resultFail
				throw "CPUOfflineKernelBuild.sh finished with FAILED state!"
			} elseif ($state -eq "TestAborted") {
				$resultArr = $resultAborted
				throw "CPUOfflineKernelBuild.sh finished with ABORTED state!"
			} else {
				Write-LogInfo "CPUOfflineKernelBuild.sh is still running in the VM!"
			}
		}
		if ($vmCount -le 0){
			Write-LogInfo "CPUOfflineKernelBuild.sh is done successfully"
		} else {
			Throw "CPUOfflineKernelBuild.sh didn't finish in the VM!"
		}

		for ($loopCount = 1;$loopCount -le $max_stress_count;$loopCount++) {
			# ##################################################################################
			# Reboot VM
			Write-LogInfo "Rebooting VM! - Loop Count: $loopCount"
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
					$channelChangeCompleted = Run-LinuxCmd -ip $VMData.PublicIP -port $VMData.SSHPort -username $user -password $password -command "cat ~/constants.sh | grep job_completed=0" -runAsSudo
					if ($channelChangeCompleted -ne "job_completed=0") {
						throw "channel_change.sh finished on $($VMData.RoleName) but job was not successful!"
					} else {
						Write-LogInfo "channel_change.sh finished on $($VMData.RoleName)"
						$vmCount--
					}
					break
				} elseif ($state -eq "TestSkipped") {
					$resultArr = $resultSkipped
					throw "channel_change.sh finished with SKIPPED state!"
				} elseif ($state -eq "TestFailed") {
					$resultArr = $resultFail
					throw "channel_change.sh finished with FAILED state!"
				} elseif ($state -eq "TestAborted") {
					$resultArr = $resultAborted
					throw "channel_change.sh finished with ABORTED state!"
				} else {
					Write-LogInfo "channel_change.sh is still running in the VM!"
				}
			}
			if ($vmCount -le 0){
				Write-LogInfo "channel_change.sh is done"
			} else {
				Throw "channel_change.sh didn't finish in the VM!"
			}

			# Revert state.txt and remove job_completed=0
			$state = Run-LinuxCmd -ip $VMData.PublicIP -port $VMData.SSHPort -username $user -password $password -command "cat /dev/null > ~/state.txt" -runAsSudo
			sed -i -e 's/job_completed=0//g' ~/constants.sh
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

	# Collect the TestExecution.log file
	Copy-RemoteFiles -downloadFrom $ServerVMData.PublicIP -port $ServerVMData.SSHPort -username $user -password $password -download -downloadTo $LogDir -files "~/TestExecution.log"

	$currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
	return $currentTestResult
}

Main -AllVmData $AllVmData -CurrentTestData $CurrentTestData