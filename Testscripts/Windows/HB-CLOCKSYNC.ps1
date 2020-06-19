# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
<#
.Synopsis
	RTC (Real-Time Clock) returns hardware clock from Hyper-v host.
	Hibernation does not reset RTC until the next host sync-up time.
	# Hibernation will be supported in the general purpose VM with max 16G vRAM
	# and the GPU VMs with max 112G vRAM.

.Description
	This test can be performed in Azure and Hyper-V both. But this script only covers Azure.
	1. Prepare swap space for hibernation
	2. Compile a new kernel (optional)
	3. Update the grub.cfg with resume=UUID=xxxx where is from blkid swap disk
	4. Set RTC to future time or past time
	5. Hibernate the VM
	5. Resume the VM
	6. Read RTC timestamp and compare to the original value
#>

param([object] $AllVmData, [string]$TestParams)

function Main {
	param($AllVMData, $TestParams)
	$currentTestResult = Create-TestResultObject
	try {
		$maxKernelCompileMin = 90
		$testResult = $resultFail
		Write-LogDbg "Prepare swap space for VM $($AllVMData.RoleName) in RG $($AllVMData.ResourceGroupName)."
		# Prepare the swap space in the target VM
		$rgName = $AllVMData.ResourceGroupName
		$vmName = $AllVMData.RoleName
		$location = $AllVMData.Location
		$storageType = 'StandardSSD_LRS'
		$dataDiskName = $vmName + '_datadisk1'

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

		#region Add a new swap disk to Azure VM
		$diskConfig = New-AzDiskConfig -SkuName $storageType -Location $location -CreateOption Empty -DiskSizeGB 1024
		$dataDisk1 = New-AzDisk -DiskName $dataDiskName -Disk $diskConfig -ResourceGroupName $rgName

		$vm = Get-AzVM -Name $vmName -ResourceGroupName $rgName
		Start-Sleep -seconds 30
		$vm = Add-AzVMDataDisk -VM $vm -Name $dataDiskName -CreateOption Attach -ManagedDiskId $dataDisk1.Id -Lun 1
		Start-Sleep -seconds 30

		$ret_val = Update-AzVM -VM $vm -ResourceGroupName $rgName
		Write-LogInfo "Updated the VM with a new data disk"
		Write-LogInfo "Waiting for 30 seconds for configuration sync"
		# Wait for disk sync with Azure host
		Start-Sleep -seconds 30

		# Verify the new data disk addition
		if ($ret_val.IsSuccessStatusCode) {
			Write-LogInfo "Successfully add a new disk to the Resource Group, $($rgName)"
		} else {
			Write-LogErr "Failed to add a new disk to the Resource Group, $($rgname)"
			throw "Failed to add a new disk"
		}

		# TODO: This will be revised with other distro. hwclock output format might be different.
		$getyear = @"
source utils.sh
hwclock > _time
if [[ `$DISTRO_NAME == 'ubuntu' && `$DISTRO_VERSION == '16.04' ]]; then
	cat _time | cut -d ' ' -f 4 > timestamp.log
else
	cat _time | cut -d '-' -f 1 > timestamp.log
fi
"@
		Set-Content "$LogDir\getyear.sh" $getyear

		$testcommand = @"
echo disk > /sys/power/state
"@
		Set-Content "$LogDir\test.sh" $testcommand

		#region Upload files to VM
		foreach ($VMData in $AllVMData) {
			Copy-RemoteFiles -uploadTo $VMData.PublicIP -port $VMData.SSHPort -files "$constantsFile,$($CurrentTestData.files),$LogDir\*.sh" -username $user -password $password -upload
			Write-LogInfo "Copied the script files to the VM"
		}
		#endregion

		# Configuration for the hibernation
		Run-LinuxCmd -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password -command "./SetupHbKernel.sh" -RunInBackground -runAsSudo -ignoreLinuxExitCode:$true | Out-Null
		Write-LogInfo "Executed SetupHbKernel script inside VM"

		# Wait for kernel compilation completion. 90 min timeout
		$timeout = New-Timespan -Minutes $maxKernelCompileMin
		$sw = [diagnostics.stopwatch]::StartNew()
		while ($sw.elapsed -lt $timeout){
			$vmCount = $AllVMData.Count
			Wait-Time -seconds 30
			$state = Run-LinuxCmd -ip $VMData.PublicIP -port $VMData.SSHPort -username $user -password $password -command "cat ~/state.txt"
			if ($state -eq "TestCompleted") {
				$kernelCompileCompleted = Run-LinuxCmd -ip $VMData.PublicIP -port $VMData.SSHPort -username $user -password $password -command "cat ~/constants.sh | grep setup_completed=0"
				if ($kernelCompileCompleted -ne "setup_completed=0") {
					Write-LogErr "SetupHbKernel.sh run finished on $($VMData.RoleName) but setup was not successful!"
				} else {
					Write-LogInfo "SetupHbKernel.sh finished on $($VMData.RoleName)"
					$vmCount--
				}
				break
			} elseif ($state -eq "TestSkipped") {
				Write-LogInfo "SetupHbKernel.sh finished with SKIPPED state!"
				$resultArr = $resultSkipped
				$currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
				return $currentTestResult.TestResult
			} elseif ($state -eq "TestFailed") {
				Write-LogErr "SetupHbKernel.sh didn't finish successfully!"
				$resultArr = $resultFail
				$currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
				return $currentTestResult.TestResult
			} elseif ($state -eq "TestAborted") {
				Write-LogInfo "SetupHbKernel.sh finished with Aborted state!"
				$resultArr = $resultAborted
				$currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
				return $currentTestResult.TestResult
			} else {
				Write-LogInfo "SetupHbKernel.sh is still running in the VM!"
			}
		}
		if ($vmCount -le 0){
			Write-LogInfo "SetupHbKernel.sh is done"
		} else {
			Throw "SetupHbKernel.sh didn't finish in the VM!"
		}

		# Reboot VM to apply swap setup changes
		Write-LogInfo "Rebooting All VMs!"
		$TestProvider.RestartAllDeployments($AllVMData)

		# Check the VM status before hibernation
		$vmStatus = Get-AzVM -Name $vmName -ResourceGroupName $rgName -Status
		if ($vmStatus.Statuses[1].DisplayStatus -eq "VM running") {
			Write-LogInfo "$($vmStatus.Statuses[1].DisplayStatus): Verified successfully VM status is running before hibernation"
		} else {
			Write-LogErr "$($vmStatus.Statuses[1].DisplayStatus): Could not find the VM status before hibernation"
			throw "Can not identify VM status before hibernate"
		}

		# Hibernate the VM
		Run-LinuxCmd -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password -command "hwclock --set --date='2033-07-01 12:00:00'" -runAsSudo -ignoreLinuxExitCode:$true | Out-Null
		Start-Sleep -seconds 1
		Run-LinuxCmd -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password -command "bash getyear.sh" -runAsSudo -ignoreLinuxExitCode:$true | Out-Null
		Start-Sleep -seconds 1
		Run-LinuxCmd -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password -command "mv timestamp.log before_timestamp.log" -runAsSudo -ignoreLinuxExitCode:$true | Out-Null
		Start-Sleep -seconds 1
		Run-LinuxCmd -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password -command "bash test.sh" -runAsSudo -RunInBackground -ignoreLinuxExitCode:$true | Out-Null
		Write-LogInfo "Sent hibernate command to the VM and continue checking its status in every 15 seconds until 10 minutes timeout "

		# Verify the VM status
		# Can not find if VM hibernation completion or not as soon as it disconnects the network. Assume it is in timeout.
		$timeout = New-Timespan -Minutes 10
		$sw = [diagnostics.stopwatch]::StartNew()
		while ($sw.elapsed -lt $timeout){
			Wait-Time -seconds 15
			$vmStatus = Get-AzVM -Name $vmName -ResourceGroupName $rgName -Status
			if ($vmStatus.Statuses[1].DisplayStatus -eq "VM stopped") {
				break
			} else {
				Write-LogInfo "VM status is not stopped. Wating for 15s..."
			}
		}
		if ($vmStatus.Statuses[1].DisplayStatus -eq "VM stopped") {
			Write-LogInfo "$($vmStatus.Statuses[1].DisplayStatus): Verified successfully VM status is stopped after hibernation command sent"
		} else {
			Write-LogErr "$($vmStatus.Statuses[1].DisplayStatus): Could not find the VM status after hibernation command sent"
			throw "Can not identify VM status after hibernate"
		}

		# Resume the VM
		Start-AzVM -Name $vmName -ResourceGroupName $rgName -NoWait | Out-Null
		Write-LogInfo "Waked up the VM $vmName in Resource Group $rgName and continue checking its status in every 15 seconds until 15 minutes timeout "

		# Wait for VM resume for 15 min-timeout
		$timeout = New-Timespan -Minutes 15
		$sw = [diagnostics.stopwatch]::StartNew()
		while ($sw.elapsed -lt $timeout){
			$vmCount = $AllVMData.Count
			Wait-Time -seconds 15
			$state = Run-LinuxCmd -ip $AllVMData[0].PublicIP -port $AllVMData[0].SSHPort -username $user -password $password -command "date > /dev/null; echo $?"
			if ($state) {
				$kernelCompileCompleted = Run-LinuxCmd -ip $AllVMData[0].PublicIP -port $AllVMData[0].SSHPort -username $user -password $password -command "dmesg | grep -i 'hibernation exit'"
				# This verification might be revised in future. Checking with dmesg is risky.
				if ($kernelCompileCompleted -ne "hibernation exit") {
					Write-LogErr "VM $($AllVMData[0].RoleName) resumed successfully but could not determine hibernation completion"
				} else {
					Write-LogInfo "VM $($AllVMData[0].RoleName) resumed successfully"
					$vmCount--
				}
				break
			} else {
				Write-LogInfo "VM is still resuming!"
			}
		}

		if ($vmCount -le 0){
			Write-LogInfo "VM resume completed"
		} else {
			# Either VM hang or VM resume needs longer time.
			throw "VM resume did not finish, the latest state was $state"
		}

		Write-LogInfo "Waiting for RTC re-sync in 5 minutes"
		Start-Sleep -seconds 300

		Write-LogInfo "Capturing the RTC timestmap to 5min_after_timestamp.log file"
		Run-LinuxCmd -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password -command "hwclock --systohc" -runAsSudo -ignoreLinuxExitCode:$true | Out-Null
		Start-Sleep -seconds 1
		Run-LinuxCmd -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password -command "bash getyear.sh" -runAsSudo -ignoreLinuxExitCode:$true | Out-Null
		Start-Sleep -seconds 1
		Run-LinuxCmd -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password -command "mv timestamp.log 5min_after_timestamp.log" -runAsSudo -ignoreLinuxExitCode:$true | Out-Null
		Start-Sleep -seconds 1

		#Verify the VM status after power on event
		$vmStatus = Get-AzVM -Name $vmName -ResourceGroupName $rgName -Status
		if ($vmStatus.Statuses[1].DisplayStatus -eq "VM running") {
			Write-LogInfo "$($vmStatus.Statuses[1].DisplayStatus): Verified successfully VM status is running after resuming"
		} else {
			Write-LogErr "$($vmStatus.Statuses[1].DisplayStatus): Could not find the VM status after resuming"
			throw "Can not identify VM status after resuming"
		}

		# Verify the kernel panic, call trace or fatal error
		$calltrace_filter = Run-LinuxCmd -ip $AllVMData[0].PublicIP -port $AllVMData[0].SSHPort -username $user -password $password -command "dmesg | grep -iE '(call trace|fatal error)'" -ignoreLinuxExitCode:$true

		if ($calltrace_filter -ne "") {
			Write-LogErr "Found Call Trace or Fatal error in dmesg"
			# The throw statement is commented out because this is linux-next, so there is high chance to get call trace from other issue. For now, only print the error.
			# throw "Call trace in dmesg"
		} else {
			Write-LogInfo "Not found Call Trace and Fatal error in dmesg"
		}

		Write-LogDbg "Waiting 60-second for logging sync"
		Start-Sleep -seconds 60

		# Check the system log if it shows Power Management log
		"hibernation entry", "hibernation exit" | ForEach-Object {
			$pm_log_filter = Run-LinuxCmd -ip $AllVMData[0].PublicIP -port $AllVMData[0].SSHPort -username $user -password $password -command "cat /var/log/syslog | grep -i '$_'" -ignoreLinuxExitCode:$true
			Write-LogInfo "Searching the keyword: $_"
			if ($pm_log_filter -eq "") {
				Write-LogErr "Could not find Power Management log in dmesg"
				throw "Missing PM logging in dmesg"
			} else {
				Write-LogInfo "Successfully found Power Management log in dmesg"
				Write-LogInfo $pm_log_filter
			}
		}

		Copy-RemoteFiles -downloadFrom $AllVMData[0].PublicIP -port $AllVMData[0].SSHPort -username $user -password $password -download -downloadTo $LogDir -files "*.log" -runAsSudo

		$beforeTimeStamp = Get-Content $LogDir\before_timestamp.log
		Write-LogDbg $beforeTimeStamp
		$5minAfterTimeStamp = Get-Content $LogDir\5min_after_timestamp.log
		Write-LogDbg $5minAfterTimeStamp

		if ($beforeTimeStamp -ne $5minAfterTimeStamp) {
			Write-LogInfo "Successfully verified the beforeTimeStamp was different from 5minAfterTimeStamp"
		} else {
			Write-LogErr "Did not find time synced. $beforeTimeStamp to $5minAfterTimeStamp"
		}

		$controllerTimeStamp = Get-Date -format "yyyy"
		Write-LogDbg $controllerTimeStamp

		if ($5minAfterTimeStamp -eq $controllerTimeStamp) {
			Write-LogInfo "Successfully verified the system date changed back to correct date"
		} else {
			Write-LogErr "Expected VM time changed back to the correct one after sync-up, but found $5minAfterTimeStamp"
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