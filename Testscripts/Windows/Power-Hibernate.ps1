# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
<#
.Synopsis
	Perform a simple VM hibernation in Azure or Hyper-V

.Description
	This test can be performend in Azure and Hyper-V both.
	1. Prepare swap space for hibernation
	2. Compile a new kernel (optional)
	3. Update the grup.cfg with resume=UUID=xxxx where is from blkid swap disk
	4. Hibernate the VM, and verify the VM status
	5. Resume the VM and verify the VM status.
	6. Verify no kernel panic or call trace
#>

param([object] $AllVmData, [string]$TestParams)

function Main {
	param($AllVMData, $TestParams)
	$currentTestResult = Create-TestResultObject
	try {
		$testResult = "FAIL"
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
			if ($TestParam -imatch "hb_url") {
				$hb_url = $TestParam
			}
		}

		Write-LogInfo "constants.sh created successfully..."
		#endregion

		#region Add a new swap disk to Azure VM
		$diskConfig = New-AzDiskConfig -SkuName $storageType -Location $location -CreateOption Empty -DiskSizeGB 1024
		$dataDisk1 = New-AzDisk -DiskName $dataDiskName -Disk $diskConfig -ResourceGroupName $rgName

		$vm = Get-AzVM -Name $vmName -ResourceGroupName $rgName
		$vm = Add-AzVMDataDisk -VM $vm -Name $dataDiskName -CreateOption Attach -ManagedDiskId $dataDisk1.Id -Lun 1

		Update-AzVM -VM $vm -ResourceGroupName $rgName

		# Wait for disk sync with Azure host
		Start-Sleep -s 10

		#region Upload files to master VM
		foreach ($VMData in $AllVMData) {
			Copy-RemoteFiles -uploadTo $VMData.PublicIP -port $VMData.SSHPort `
				-files "$constantsFile,$($CurrentTestData.files)" -username $user -password $password -upload -runAsSudo
				Write-LogInfo "Copied the script files to the VM, $VMData.PublicIP"
		}
		#endregion

		# Run kernel compilation if defined
		# Configuration for the hibernation
		if ($hb_url -ne "") {
			Run-LinuxCmd -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password -command "/root/SetupHbKernel.sh" -ignoreLinuxExitCode:$true -runAsSudo | Out-Null
			Write-LogInfo "Executed SetupHbKernel script inside VM"

			# Wait for kernel compilation completion. 20 min timeout
			$timeout = New-Timespan -Minutes 20
			$sw = [diagnostics.stopwatch]::StartNew()
			while ($sw.elapsed -lt $timeout){
				$vmCount = $AllVMData.Count
				foreach ($VMData in $AllVMData) {
					Wait-Time -seconds 15
					$state = Run-LinuxCmd -ip $VMData.PublicIP -port $VMData.SSHPort -username $user -password $password "cat /root/state.txt" -runAsSudo
					if ($state -eq "TestCompleted") {
						$kernelCompileCompleted = Run-LinuxCmd -ip $VMData.PublicIP -port $VMData.SSHPort -username $user -password $password "cat /root/constants.sh | grep setup_completed=0" -runAsSudo
						if ($kernelCompileCompleted -ne "setup_completed=0") {
							Throw "SetupHbKernel.sh run finished on $($VMData.RoleName) but setup was not successful!"
						}
						Write-LogInfo "SetupHbKernel.sh finished on $($VMData.RoleName)"
						$vmCount--
					}

					if ($state -eq "TestSkipped") {
						Write-LogInfo "SetupHbKernel.sh finished with SKIPPED state!"
						$testResult = "SKIPPED"
						return "SKIPPED"
					}

					if (($state -eq "TestFailed") -or ($state -eq "TestAborted")) {
						Write-LogErr "SetupHbKernel.sh didn't finish successfully!"
						$testResult = $resultAborted
						return $resultAborted
					}
				}
				if ($vmCount -eq 0){
					break
				}
				Write-LogInfo "SetupHbKernel.sh is still running on $vmCount VM(s)!"
			}
			if ($vmCount -eq 0){
				Write-LogInfo "SetupHbKernel.sh is done"
			} else {
				Throw "SetupHbKernel.sh didn't finish at least on one VM!"
			}
		}

		# Reboot VM to apply swap setup changes
		Write-LogInfo "Rebooting All VMs!"
		$TestProvider.RestartAllDeployments($AllVMData)

		# Check the VM status before hibernation
		$vmStatus = Get-AzVM -Name $vmName -ResourceGroupName $rgName -Status
		if ($vmStatus.Statuses[1].DisplayStatus = "VM running") {
			Write-LogInfo "$vmStatus.Statuses[1].DisplayStatus: Verified VM status is running before hibernation"
		} else {
			Write-LogErr "$vmStatus.Statuses[1].DisplayStatus: Could not find the VM status before hibernation"
			throw "Can not identify VM status before hibernate"
		}

		# Hibernate the VM
		Run-LinuxCmd -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password -command "sudo ./test.sh" -ignoreLinuxExitCode:$true -runAsSudo | Out-Null
		Write-LogInfo "Sent hibernate command to the system"
		Start-Sleep -s 120

		# Verify the VM status
		$vmStatus = Get-AzVM -Name $vmName -ResourceGroupName $rgName -Status
		if ($vmStatus.Statuses[1].DisplayStatus = "VM stopped") {
			Write-LogInfo "$vmStatus.Statuses[1].DisplayStatus: Verified VM status is running after hibernation command sent"
		} else {
			Write-LogInfo "$vmStatus.Statuses[1].DisplayStatus: Could not find the VM status after hibernation command sent"
			throw "Can not identify VM ststus after hibernate"
		}

		# Resume the VM
		Start-AzVM -Name $vmName -ResourceGroupName $rgName -NoWait | Out-Null
		Write-LogInfo "Waked up the VM $vmName in Resource Group $rgName"
		Start-Sleep -s 120

		#Verify the VM status after power on event
		$vmStatus = Get-AzVM -Name $vmName -ResourceGroupName $rgName -Status
		if ($vmStatus.Statuses[1].DisplayStatus = "VM running") {
			Write-LogInfo "$vmStatus.Statuses[1].DisplayStatus: Verified VM status is running before resuming"
		} else {
			Write-LogInfo "$vmStatus.Statuses[1].DisplayStatus: Could not find the VM status before resuming"
			throw "Can not identify VM status after resuming"
		}

		# Verify the kernel panic or call trace
		$calltrace_filter = Run-LinuxCmd -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password -command "dmesg | grep -i 'call trace'" -ignoreLinuxExitCode:$true -runAsSudo

		if ($calltrace_filter -ne "") {
			Write-LogInfo "Found Call Trace in dmesg"
			throw "Call trace in dmesg"
		} else {
			Write-LogInfo "Not found call trace in dmesg"
		}

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