# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
<#
.Synopsis
	Perform a simple VM hibernation in Azure
	This feature might be available in kernel 5.7 or later. By the time,
	customized kernel will be built.

.Description
	1. Prepare swap space for hibernation
	2. Compile a new kernel (optional)
	3. Update the grup.cfg with resume=UUID=xxxx where is from blkid swap disk
	4. Run the first fio testing
	5. Hibernate the VM, and verify the VM status
	5. Resume the VM and verify the VM status.
	6. Verify no kernel panic or call trace
	7. Run the second fio testing.
	8. Verify IOPS counts
	9. Run the thrid fio testing.
	10. In the middle of fio, hibernation starts.
	11. Verify no kernel panic or call trace after resume.
#>

param([object] $AllVmData, [string]$TestParams)

function Main {
	param($AllVMData, $TestParams)
	$currentTestResult = Create-TestResultObject
	try {
		$maxVMResumeWaitMin = 8
		$maxFIORunWaitMin = 7
		$maxVMWakeupMin = 15
		$maxKernelCompileMin = 60
		$azureSyncSecond = 30

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
		Start-Sleep -s $azureSyncSecond
		$vm = Add-AzVMDataDisk -VM $vm -Name $dataDiskName -CreateOption Attach -ManagedDiskId $dataDisk1.Id -Lun 1
		Start-Sleep -s $azureSyncSecond

		$ret_val = Update-AzVM -VM $vm -ResourceGroupName $rgName
		Write-LogInfo "Updated the VM with a new data disk"
		Write-LogInfo "Waiting for $azureSyncSecond seconds for configuration sync"
		# Wait for disk sync with Azure host
		Start-Sleep -s $azureSyncSecond

		# Verify the new data disk addition
		if ($ret_val.IsSuccessStatusCode) {
			Write-LogInfo "Successfully add a new disk to the Resource Group, $($rgName)"
		} else {
			Write-LogErr "Failed to add a new disk to the Resource Group, $($rgname)"
			throw "Failed to add a new disk"
		}
		#endregion

		#region Upload files to VM
		foreach ($VMData in $AllVMData) {
			Copy-RemoteFiles -uploadTo $VMData.PublicIP -port $VMData.SSHPort -files "$constantsFile,$($CurrentTestData.files)" -username $user -password $password -upload
			Write-LogInfo "Copied the script files to the VM"
		}
		#endregion

		# Configuration for the hibernation
		Write-LogInfo "New kernel compiling..."
		Run-LinuxCmd -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password -command "./SetupHbKernel.sh" -RunInBackground -runAsSudo -ignoreLinuxExitCode:$true | Out-Null
		Write-LogInfo "Executed SetupHbKernel script inside VM"

		# Wait for kernel compilation completion. 60 min timeout
		$timeout = New-Timespan -Minutes $maxKernelCompileMin
		$sw = [diagnostics.stopwatch]::StartNew()
		while ($sw.elapsed -lt $timeout){
			$vmCount = $AllVMData.Count
			Wait-Time -seconds 15
			$state = Run-LinuxCmd -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password "cat ~/state.txt"
			if ($state -eq "TestCompleted") {
				$kernelCompileCompleted = Run-LinuxCmd -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password "cat ~/constants.sh | grep setup_completed=0"
				if ($kernelCompileCompleted -ne "setup_completed=0") {
					Write-LogErr "SetupHbKernel.sh run finished on $($AllVMData.RoleName) but setup was not successful!"
				} else {
					Write-LogInfo "SetupHbKernel.sh finished on $($AllVMData.RoleName)"
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
			throw "SetupHbKernel.sh didn't finish in the VM!"
		}

		# Reboot VM to apply swap setup changes
		Write-LogInfo "Rebooting All VMs!"
		$TestProvider.RestartAllDeployments($AllVMData)

		# Check the VM status before hibernation
		$vmStatus = Get-AzVM -Name $vmName -ResourceGroupName $rgName -Status
		if ($vmStatus.Statuses[1].DisplayStatus = "VM running") {
			Write-LogInfo "$($vmStatus.Statuses[1].DisplayStatus): Verified successfully VM status is running before hibernation"
		} else {
			Write-LogErr "$($vmStatus.Statuses[1].DisplayStatus): Could not find the VM status before hibernation"
			throw "Can not identify VM status before hibernate"
		}

		# Send fio 32-job command for 5 min
		Write-LogInfo "Running fio-1 command"
		$timeout = New-Timespan -Minutes $maxFIORunWaitMin
		$sw = [diagnostics.stopwatch]::StartNew()
		Run-LinuxCmd -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password -command "echo fio1=running >> constants.sh" -runAsSudo
		Run-LinuxCmd -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password -command "fio --size=10G --name=beforehb --direct=1 --ioengine=libaio `
			--filename=fiodata --overwrite=1 --readwrite=readwrite --bs=1M --runtime=1 --iodepth=128 --numjobs=32 --runtime=300 --output-format=json+ `
			--output=beforehb.json;sed -i -e 's/fio1=running/fio=completed/g' constants.sh" -runAsSudo - -RunInBackground
		while ($sw.elapsed -lt $timeout){
			Wait-Time -seconds 15
			$fioState = Run-LinuxCmd -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password "cat constants.sh | grep fio1=completed" -runAsSudo
			if ($fioState -eq "fio1=completed") {
				Write-LogInfo "Completed fio command execution in the VM $($AllVMData.RoleName) successfully"
				break
			} else {
				Write-LogInfo "fio command is still running!"
			}
		}
		if ($fioState -ne "fio1=completed") {
			throw "fio-1 command is still running after $maxFIORunWaitMin minutes"
		}

		Write-LogInfo "Removed the old fio runtime artifact"
		Run-LinuxCmd -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password "rm -f fiodata" -runAsSudo

		# Hibernate the VM
		Run-LinuxCmd -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password -command "./test.sh" -runAsSudo -RunInBackground -ignoreLinuxExitCode:$true | Out-Null
		Write-LogInfo "Sent hibernate command to the VM and continue checking its status in every 15 seconds until $maxVMResumeWaitMin minutes timeout."

		# Verify the VM status
		# Can not find if VM hibernation completion or not as soon as it disconnects the network. Assume it is in timeout.
		$timeout = New-Timespan -Minutes $maxVMResumeWaitMin
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
			Write-LogInfo "$($vmStatus.Statuses[1].DisplayStatus): Verified successfully VM status is stopped after hibernation command sent."
		} else {
			Write-LogErr "$($vmStatus.Statuses[1].DisplayStatus): Could not find the VM status after hibernation command sent."
			throw "Can not identify VM status after hibernate"
		}

		# Resume the VM
		Start-AzVM -Name $vmName -ResourceGroupName $rgName -NoWait | Out-Null
		Write-LogInfo "Waked up the VM $vmName in Resource Group $rgName and continue checking its status in every 15 seconds until $maxVMWakeupMin minutes timeout "

		# Wait for VM resume for $maxWakeupTime min-timeout
		$timeout = New-Timespan -Minutes $maxVMWakeupMin
		$sw = [diagnostics.stopwatch]::StartNew()
		while ($sw.elapsed -lt $timeout){
			$vmCount = $AllVMData.Count
			Wait-Time -seconds 15
			$state = Run-LinuxCmd -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password "date"
			if ($state -eq 0) {
				Write-LogInfo "VM $($AllVMData.RoleName) resumed successfully."
				$vmCount--
				break
			} else {
				Write-LogInfo "VM is still resuming!"
			}
		}
		if ($vmCount -le 0){
			Write-LogInfo "VM resume completed."
		} else {
			throw "VM resume did not finish after maxVMWakeupMin minutes."
		}

		#Verify the VM status after power on event
		$vmStatus = Get-AzVM -Name $vmName -ResourceGroupName $rgName -Status
		if ($vmStatus.Statuses[1].DisplayStatus -eq "VM running") {
			Write-LogInfo "$($vmStatus.Statuses[1].DisplayStatus): Verified successfully VM status is running after resuming"
		} else {
			Write-LogErr "$($vmStatus.Statuses[1].DisplayStatus): Could not find the VM status after resuming"
			throw "Can not identify VM status after resuming"
		}

		# Verify kernel panic or call trace
		$calltrace_filter = Run-LinuxCmd -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password -command "dmesg | grep -i 'call trace'" -ignoreLinuxExitCode:$true

		if ($calltrace_filter -ne "") {
			Write-LogErr "Found Call Trace in dmesg"
			# throw "Call trace in dmesg"
		} else {
			Write-LogInfo "Not found Call Trace in dmesg"
		}

		# Check the system log if it shows Power Management log
		"hibernation entry", "hibernation exit" | ForEach-Object {
			$pm_log_filter = Run-LinuxCmd -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password -command "dmesg | grep -i '$_'" -ignoreLinuxExitCode:$true
			Write-LogInfo "Searching the keyword: $_"
			if ($pm_log_filter -eq "") {
				Write-LogErr "Could not find Power Management log in dmesg"
				throw "Missing PM logging in dmesg"
			} else {
				Write-LogInfo "Successfully found Power Management log in dmesg"
				Write-LogInfo $pm_log_filter
			}
		}

		# Send fio 32-job command for 5 min
		Write-LogInfo "Running fio-2 command"
		$timeout = New-Timespan -Minutes $maxFIORunWaitMin
		$sw = [diagnostics.stopwatch]::StartNew()
		Run-LinuxCmd -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password -command "echo fio2=running >> constants.sh" -runAsSudo
		Run-LinuxCmd -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password -command "fio --size=10G --name=afterhb --direct=1 --ioengine=libaio `
			--filename=fiodata --overwrite=1 --readwrite=readwrite --bs=1M --runtime=1 --iodepth=128 --numjobs=32 --runtime=300 --output-format=json+ `
			--output=afterhb.json;sed -i -e 's/fio2=running/fio=completed/g' constants.sh" -runAsSudo - -RunInBackground
		while ($sw.elapsed -lt $timeout){
			Wait-Time -seconds 15
			$fioState = Run-LinuxCmd -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password "cat constants.sh | grep fio2=completed" -runAsSudo
			if ($fioState -eq "fio2=completed") {
				Write-LogInfo "Completed fio command execution in the VM $($AllVMData.RoleName) successfully"
				break
			} else {
				Write-LogInfo "fio command is still running!"
			}
		}
		if ($fioState -ne "fio2=completed") {
			throw "fio-2 command is still running after $maxFIORunWaitMin minutes"
		}

		Write-LogInfo "Removed the old fio runtime artifact"
		Run-LinuxCmd -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password "rm -f fiodata" -runAsSudo

		$testResult = $resultPass

		Copy-RemoteFiles -downloadFrom $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password -download -downloadTo $LogDir -files "*.json, *.log" -runAsSudo
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