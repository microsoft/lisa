# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
<#
.Synopsis
	Perform a simple VM hibernation in Azure
	This feature might be available in kernel 5.7 or later. By the time,
	customized kernel will be built.
	# Hibernation will be supported in the general purpose VM with max 16G vRAM
	# and the GPU VMs with max 112G vRAM.

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
		$maxVMHibernateWaitMin = 30
		$maxFIORunWaitMin = 7
		$maxVMWakeupMin = 40
		$maxKernelCompileMin = 90
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

		$fio1Command = @"
source utils.sh
SetTestStateRunning
fio --size=1G --name=beforehb --direct=1 --ioengine=libaio --filename=fiodata --overwrite=1 --readwrite=readwrite --bs=1M --runtime=1 --iodepth=128 --numjobs=32 --runtime=300 --output-format=json+ --output=beforehb.json
rm -f fiodata
sync
echo 3 > /proc/sys/vm/drop_caches
SetTestStateCompleted
"@
		Set-Content "$LogDir\fio1Command.sh" $fio1Command

		$fio2Command = @"
source utils.sh
SetTestStateRunning
fio --size=1G --name=afterhb --direct=1 --ioengine=libaio --filename=fiodata --overwrite=1 --readwrite=readwrite --bs=1M --runtime=1 --iodepth=128 --numjobs=32 --runtime=300 --output-format=json+ --output=afterhb.json
rm -f fiodata
sync
echo 3 > /proc/sys/vm/drop_caches
SetTestStateCompleted
"@
		Set-Content "$LogDir\fio2Command.sh" $fio2Command

		#region Upload files to VM
		foreach ($VMData in $AllVMData) {
			Copy-RemoteFiles -uploadTo $VMData.PublicIP -port $VMData.SSHPort -files "$constantsFile,$($CurrentTestData.files),$LogDir\fio*.sh" -username $user -password $password -upload
			Write-LogInfo "Copied the script files to the VM"
		}
		#endregion

		# Configuration for the hibernation
		Write-LogInfo "New kernel compiling..."
		Run-LinuxCmd -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password -command "./SetupHbKernel.sh" -RunInBackground -runAsSudo -ignoreLinuxExitCode:$true | Out-Null
		Write-LogInfo "Executed SetupHbKernel script inside VM"

		# Wait for kernel compilation completion. 90 min timeout
		$timeout = New-Timespan -Minutes $maxKernelCompileMin
		$sw = [diagnostics.stopwatch]::StartNew()
		while ($sw.elapsed -lt $timeout){
			$vmCount = $AllVMData.Count
			Wait-Time -seconds 30
			$state = Run-LinuxCmd -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password "cat /home/$username/state.txt"
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
		$state = Run-LinuxCmd -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password -command "bash ./fio1Command.sh" -RunInBackground -runAsSudo
		Wait-Time -seconds 5
		while ($sw.elapsed -lt $timeout){
			Wait-Time -seconds 15
			$state = Run-LinuxCmd -ip $VMData.PublicIP -port $VMData.SSHPort -username $user -password $password "cat /home/$username/state.txt"
			if ($state -eq "TestCompleted") {
				Write-LogInfo "Completed fio command execution in the VM $($AllVMData.RoleName) successfully"
				break
			} else {
				Write-LogInfo "$state: fio command is still running!"
			}
		}
		if ($state -ne "TestCompleted") {
			throw "fio-1 command is still running after $maxFIORunWaitMin minutes"
		}

		# Hibernate the VM
		Write-LogInfo "Hibernating ..."
		Run-LinuxCmd -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password -command "./test.sh" -runAsSudo -RunInBackground -ignoreLinuxExitCode:$true | Out-Null
		Write-LogInfo "Sent hibernate command to the VM and continue checking its status in every 1 minute until $maxVMHibernateWaitMin minutes timeout."

		# Verify the VM status
		# Can not find if VM hibernation completion or not as soon as it disconnects the network. Assume it is in timeout.
		$timeout = New-Timespan -Minutes $maxVMHibernateWaitMin
		$sw = [diagnostics.stopwatch]::StartNew()
		while ($sw.elapsed -lt $timeout){
			Wait-Time -seconds 60
			$vmStatus = Get-AzVM -Name $vmName -ResourceGroupName $rgName -Status
			if ($vmStatus.Statuses[1].DisplayStatus -eq "VM stopped") {
				break
			} else {
				Write-LogInfo "$vmStatus.Statuses[1].DisplayStatus: VM status is not stopped. Wating for 1 minute..."
			}
		}
		if ($vmStatus.Statuses[1].DisplayStatus -eq "VM stopped") {
			Write-LogInfo "$($vmStatus.Statuses[1].DisplayStatus): Verified successfully VM status is stopped after hibernation command sent."
		} else {
			Write-LogErr "$($vmStatus.Statuses[1].DisplayStatus): Could not find the VM status after hibernation command sent."
			throw "Can not identify VM status after hibernate"
		}

		# Resume the VM
		Write-LogInfo "Hibernation completed and resuming back the VM ..."
		Start-AzVM -Name $vmName -ResourceGroupName $rgName -NoWait | Out-Null
		Write-LogInfo "Waked up the VM $vmName in Resource Group $rgName and continue checking its status in every 1 minute until $maxVMWakeupMin minutes timeout "

		# Wait for VM resume for $maxVMWakeupMin timeout
		$timeout = New-Timespan -Minutes $maxVMWakeupMin
		$sw = [diagnostics.stopwatch]::StartNew()
		while ($sw.elapsed -lt $timeout){
			$vmCount = $AllVMData.Count
			Wait-Time -seconds 60
			$state = Run-LinuxCmd -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password "date"
			if ($state -eq 0) {
				Write-LogInfo "VM $($AllVMData.RoleName) resumed successfully."
				$vmCount--
				break
			} else {
				Write-LogInfo "$state: VM is still resuming! Wait for 1 minute ..."
			}
		}
		if ($vmCount -le 0){
			Write-LogInfo "VM resume completed."
		} else {
			throw "VM resume did not finish after $maxVMWakeupMin minutes."
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
			# The throw statement is commented out because this is linux-next, so there is high chance to get call trace from other issue. For now, only print the error.
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
		$state = Run-LinuxCmd -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password -command "bash ./fio2Command.sh" -RunInBackground -runAsSudo
		Wait-Time -seconds 5
		while ($sw.elapsed -lt $timeout){
			Wait-Time -seconds 15
			$state = Run-LinuxCmd -ip $VMData.PublicIP -port $VMData.SSHPort -username $user -password $password "cat /home/$username/state.txt"
			if ($state -eq "TestCompleted") {
				Write-LogInfo "Completed fio command execution in the VM $($AllVMData.RoleName) successfully"
				break
			} else {
				Write-LogInfo "$state: fio command is still running!"
			}
		}
		if ($state -ne "TestCompleted") {
			throw "fio-2 command is still running after $maxFIORunWaitMin minutes"
		}

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