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
				-files "$constantsFile,$($CurrentTestData.files)" -username $user -password $password -upload
				Write-LogInfo "Copied the script files to the VM"
		}
		#endregion

		# Run kernel compilation if defined
		# Configuration for the hibernation
		if ($hb_url -ne "") {
			Run-LinuxCmd -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password -command "./SetupHbKernel.sh" -RunInBackground -runAsSudo -ignoreLinuxExitCode:$true | Out-Null
			Write-LogInfo "Executed SetupHbKernel script inside VM"

			# Wait for kernel compilation completion. 20 min timeout
			$timeout = New-Timespan -Minutes 30
			$sw = [diagnostics.stopwatch]::StartNew()
			while ($sw.elapsed -lt $timeout){
				$vmCount = $AllVMData.Count
				
				Wait-Time -seconds 15
				$state = Run-LinuxCmd -ip $VMData.PublicIP -port $VMData.SSHPort -username $user -password $password "cat ~/state.txt"
				if ($state -eq "TestCompleted") {
					$kernelCompileCompleted = Run-LinuxCmd -ip $VMData.PublicIP -port $VMData.SSHPort -username $user -password $password "cat ~/constants.sh | grep setup_completed=0"
					if ($kernelCompileCompleted -ne "setup_completed=0") {
						Write-LogErr "SetupHbKernel.sh run finished on $($VMData.RoleName) but setup was not successful!"
					} else {
						Write-LogInfo "SetupHbKernel.sh finished on $($VMData.RoleName)"
						$vmCount--
					}
					break
				} elseif ($state -eq "TestSkipped") {
					Write-LogInfo "SetupHbKernel.sh finished with SKIPPED state!"
					$testResult = $resultSkipped
					return $testResult
				} elseif (($state -eq "TestFailed") -or ($state -eq "TestAborted")) {
					Write-LogErr "SetupHbKernel.sh didn't finish successfully!"
					$testResult = $resultAborted
					return $testResult
				} else {
					Write-LogInfo "SetupHbKernel.sh is still running in the VM!"
				}
			}
			if ($vmCount -le 0){
				Write-LogInfo "SetupHbKernel.sh is done"
			} else {
				Throw "SetupHbKernel.sh didn't finish in the VM!"
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
		Run-LinuxCmd -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password -command "sudo ~/test.sh" -ignoreLinuxExitCode:$true | Out-Null
		Write-LogInfo "Sent hibernate command to the VM"
		Start-Sleep -s 120

		# Verify the VM status
		$vmStatus = Get-AzVM -Name $vmName -ResourceGroupName $rgName -Status
		if ($vmStatus.Statuses[1].DisplayStatus = "VM stopped") {
			Write-LogInfo "$vmStatus.Statuses[1].DisplayStatus: Verified VM status is stopped after hibernation command sent"
		} else {
			Write-LogInfo "$vmStatus.Statuses[1].DisplayStatus: Could not find the VM status after hibernation command sent"
			throw "Can not identify VM ststus after hibernate"
		}

		# Resume the VM
		Start-AzVM -Name $vmName -ResourceGroupName $rgName -NoWait | Out-Null
		Write-LogInfo "Waked up the VM $vmName in Resource Group $rgName and waiting 180 seconds"
		Start-Sleep -s 180

		#Verify the VM status after power on event
		$vmStatus = Get-AzVM -Name $vmName -ResourceGroupName $rgName -Status
		if ($vmStatus.Statuses[1].DisplayStatus = "VM running") {
			Write-LogInfo "$vmStatus.Statuses[1].DisplayStatus: Verified VM status is running after resuming"
		} else {
			Write-LogInfo "$vmStatus.Statuses[1].DisplayStatus: Could not find the VM status after resuming"
			throw "Can not identify VM status after resuming"
		}

		# Verify the kernel panic or call trace
		$calltrace_filter = Run-LinuxCmd -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password -command "dmesg | grep -i 'call trace'" -ignoreLinuxExitCode:$true

		if ($calltrace_filter -ne "") {
			Write-LogInfo "Found Call Trace in dmesg"
			throw "Call trace in dmesg"
		} else {
			Write-LogInfo "Not found Call Trace in dmesg"
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