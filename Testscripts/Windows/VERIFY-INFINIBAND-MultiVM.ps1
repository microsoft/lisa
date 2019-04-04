# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
param([object] $AllVmData,
	[object] $CurrentTestData,
	[object] $TestProvider)

function Resolve-UninitializedIB {
	# SUSE, sometimes, needs to re-initializes IB port through rebooting
	if(@("SUSE").contains($global:detectedDistro)) {
		$cmd = "lsmod | grep -P '^(?=.*mlx5_ib)(?=.*rdma_cm)(?=.*rdma_ucm)(?=.*ib_ipoib)'"
		foreach ($VmData in $AllVMData) {
			$ibvOutput = ""
			$retries = 0
			while ($retries -lt 4) {
				$ibvOutput = Run-LinuxCmd -ip $VMData.PublicIP -port $VMData.SSHPort -username `
					$superUser -password $password $cmd -ignoreLinuxExitCode:$true
				if (-not $ibvOutput) {
					Write-LogWarn "IB is NOT initialized in $($VMData.RoleName)"
					$TestProvider.RestartAllDeployments($VmData)
					Start-Sleep -s 20
					$retries++
				} else {
					Write-LogInfo "IB is initialized in $($VMData.RoleName)"
					break
				}
			}
			if ($retries -eq 4) {
				Throw "After 3 reboots IB has NOT been initialized on $($VMData.RoleName)"
			}
		}
	}
}

function Main {
	$resultArr = @()
	$currentTestResult = Create-TestResultObject
	# Define two different users in run-time
	$superUser="root"

	try {
		$NoServer = $true
		$NoClient = $true
		$ClientMachines = @()
		$SlaveInternalIPs = ""
		foreach ($VmData in $AllVMData) {
			if ($VmData.RoleName -imatch "controller") {
				$ServerVMData = $VmData
				$NoServer = $false
			} elseif ($VmData.RoleName -imatch "Client" -or $VmData.RoleName -imatch "dependency") {
				$ClientMachines += $VmData
				$NoClient = $false
				if ($SlaveInternalIPs) {
					$SlaveInternalIPs += "," + $VmData.InternalIP
				} else {
					$SlaveInternalIPs = $VmData.InternalIP
				}
			}
		}
		if ($NoServer) {
			Throw "No any server VM defined. Be sure that, `
			server VM role name matches with the pattern `"*server*`". Aborting Test."
		}
		if ($NoClient) {
			Throw "No any client VM defined. Be sure that, `
			client machine role names matches with pattern `"*client*`" Aborting Test."
		}
		if ($ServerVMData.InstanceSize -imatch "Standard_NC") {
			Write-LogInfo "Waiting 5 minutes to finish RDMA update for NC series VMs."
			Start-Sleep -Seconds 300
		}
		$VM_Size = ($ServerVMData.InstanceSize -split "_")[1] -replace "[^0-9]",''
		Write-LogInfo "Getting VM instance size: $VM_Size"
		#region CONFIGURE VMs for TEST

		Write-LogInfo "SERVER VM details :"
		Write-LogInfo "  RoleName : $($ServerVMData.RoleName)"
		Write-LogInfo "  Public IP : $($ServerVMData.PublicIP)"
		Write-LogInfo "  SSH Port : $($ServerVMData.SSHPort)"
		$i = 1
		foreach ( $ClientVMData in $ClientMachines ) {
			Write-LogInfo "CLIENT VM #$i details :"
			Write-LogInfo "  RoleName : $($ClientVMData.RoleName)"
			Write-LogInfo "  Public IP : $($ClientVMData.PublicIP)"
			Write-LogInfo "  SSH Port : $($ClientVMData.SSHPort)"
			$i += 1
		}
		$FirstRun = $true
		Provision-VMsForLisa -AllVMData $AllVMData -installPackagesOnRoleNames "none"
		#endregion

		#region Generate constants.sh
		# We need to add extra parameters to constants.sh file apart from parameter properties defined in XML.
		# Hence, we are generating constants.sh file again in test script.

		Write-LogInfo "Generating constants.sh ..."
		$constantsFile = "$LogDir\constants.sh"
		foreach ($TestParam in $CurrentTestData.TestParameters.param ) {
			Add-Content -Value "$TestParam" -Path $constantsFile
			Write-LogInfo "$TestParam added to constants.sh"
			if ($TestParam -imatch "imb_mpi1_tests_iterations") {
				$ImbMpiTestIterations = [int]($TestParam.Replace("imb_mpi1_tests_iterations=", "").Trim('"'))
			}
			if ($TestParam -imatch "imb_rma_tests_iterations") {
				$ImbRmaTestIterations = [int]($TestParam.Replace("imb_rma_tests_iterations=", "").Trim('"'))
			}
			if ($TestParam -imatch "imb_nbc_tests_iterations") {
				$ImbNbcTestIterations = [int]($TestParam.Replace("imb_nbc_tests_iterations=", "").Trim('"'))
			}
			if ($TestParam -imatch "ib_nic") {
				$InfinibandNic = [string]($TestParam.Replace("ib_nic=", "").Trim('"'))
			}
			if ($TestParam -imatch "num_reboot") {
				$RemainingRebootIterations = [string]($TestParam.Replace("num_reboot=", "").Trim('"'))
				$ExpectedSuccessCount = [int]($TestParam.Replace("num_reboot=", "").Trim('"')) + 1
			}
		}
		Add-Content -Value "master=`"$($ServerVMData.InternalIP)`"" -Path $constantsFile
		Write-LogInfo "master=$($ServerVMData.InternalIP) added to constants.sh"
		Add-Content -Value "slaves=`"$SlaveInternalIPs`"" -Path $constantsFile
		Write-LogInfo "slaves=$SlaveInternalIPs added to constants.sh"
		Add-Content -Value "VM_Size=`"$VM_Size`"" -Path $constantsFile
		Write-LogInfo "VM_Size=$VM_Size added to constants.sh"

		Write-LogInfo "constants.sh created successfully..."
		#endregion

		#region Upload files to master VM
		foreach ($VMData in $AllVMData) {
			Copy-RemoteFiles -uploadTo $VMData.PublicIP -port $VMData.SSHPort `
				-files "$constantsFile,$($CurrentTestData.files)" -username $superUser -password $password -upload
		}
		#endregion

		Write-LogInfo "SetupRDMA.sh is called"
		# Call SetupRDMA.sh here, and it handles all packages, MPI, Benchmark installation.
		foreach ($VMData in $AllVMData) {
			Run-LinuxCmd -ip $VMData.PublicIP -port $VMData.SSHPort -username $superUser `
				-password $password "/root/SetupRDMA.sh" -RunInBackground
			Wait-Time -seconds 2
		}

		$timeout = New-Timespan -Minutes 120
		$sw = [diagnostics.stopwatch]::StartNew()
		while ($sw.elapsed -lt $timeout){
			$vmCount = $AllVMData.Count
			foreach ($VMData in $AllVMData) {
				Wait-Time -seconds 15
				$state = Run-LinuxCmd -ip $VMData.PublicIP -port $VMData.SSHPort -username $user -password $password "cat /root/state.txt" -runAsSudo
				if ($state -eq "TestCompleted") {
					$setupRDMACompleted = Run-LinuxCmd -ip $VMData.PublicIP -port $VMData.SSHPort -username $user -password $password `
						"cat /root/constants.sh | grep setup_completed=0" -runAsSudo
					if ($setupRDMACompleted -ne "setup_completed=0") {
						Throw "SetupRDMA.sh run finished on $($VMData.RoleName) but setup was not successful!"
					}
					Write-LogInfo "SetupRDMA.sh finished on $($VMData.RoleName)"
					$vmCount--
				}
			}
			if ($vmCount -eq 0){
				break
			}
			Write-LogInfo "SetupRDMA.sh is still running on $vmCount VM(s)!"
		}
		if ($vmCount -eq 0){
			Write-LogInfo "SetupRDMA.sh is done"
		} else {
			Throw "SetupRDMA.sh didn't finish at least on one VM!"
		}

		# Reboot VM to apply RDMA changes
		Write-LogInfo "Rebooting All VMs!"
		$TestProvider.RestartAllDeployments($AllVMData)

		# In some cases, IB will not be initialized after reboot
		Resolve-UninitializedIB
		$TotalSuccessCount = 0
		$Iteration = 0
		do {
			if ($FirstRun) {
				$FirstRun = $false
				$ContinueMPITest = $true
				foreach ($ClientVMData in $ClientMachines) {
					Write-LogInfo "Getting initial MAC address info from $($ClientVMData.RoleName)"
					Run-LinuxCmd -ip $ServerVMData.PublicIP -port $ServerVMData.SSHPort -username $superUser `
						-password $password "ip addr show $InfinibandNic | grep ether | awk '{print `$2}' > InitialInfiniBandMAC.txt"
				}
			} else {
				$ContinueMPITest = $true
				foreach ($ClientVMData in $ClientMachines) {
					Write-LogInfo "Step 1/2: Getting current MAC address info from $($ClientVMData.RoleName)"
					$CurrentMAC = Run-LinuxCmd -ip $ServerVMData.PublicIP -port $ServerVMData.SSHPort -username $superUser `
						-password $password "ip addr show $InfinibandNic | grep ether | awk '{print `$2}'"
					$InitialMAC = Run-LinuxCmd -ip $ServerVMData.PublicIP -port $ServerVMData.SSHPort -username $superUser `
						-password $password "cat InitialInfiniBandMAC.txt"
					if ($CurrentMAC -eq $InitialMAC) {
						Write-LogInfo "Step 2/2: MAC address verified in $($ClientVMData.RoleName)."
					} else {
						Write-LogErr "Step 2/2: MAC address swapped / changed in $($ClientVMData.RoleName)."
						$ContinueMPITest = $false
					}
				}
			}

			if ($ContinueMPITest) {
				#region EXECUTE TEST
				$Iteration += 1
				Write-LogInfo "******************Iteration - $Iteration/$ExpectedSuccessCount*******************"
				$TestJob = Run-LinuxCmd -ip $ServerVMData.PublicIP -port $ServerVMData.SSHPort -username $superUser `
					-password $password -command "/root/TestRDMA_MultiVM.sh" -RunInBackground
				#endregion

				#region MONITOR TEST
				while ((Get-Job -Id $TestJob).State -eq "Running") {
					$CurrentStatus = Run-LinuxCmd -ip $ServerVMData.PublicIP -port $ServerVMData.SSHPort -username $superUser `
						-password $password -command "tail -n 1 /root/TestExecution.log"
					Write-LogInfo "Current Test Status : $CurrentStatus"
					$temp=(Get-Job -Id $TestJob).State
					Write-LogInfo "--------------------------------------------------------------------$temp-------------------------"
					$FinalStatus = Run-LinuxCmd -ip $ServerVMData.PublicIP -port $ServerVMData.SSHPort -username $superUser `
					-password $password -command "cat /$superUser/state.txt"
					Write-LogInfo "$FinalStatus"
					Wait-Time -seconds 10
					if ($FinalStatus -ne "TestRunning") {
						Write-LogInfo "TestRDMA_MultiVM.sh finished the run!"
						break
					}
				}

				$temp=(Get-Job -Id $TestJob).State
					Write-LogInfo "-FINALLY-------------------------------------------------------------------$temp-------------------------"
				Copy-RemoteFiles -downloadFrom $ServerVMData.PublicIP -port $ServerVMData.SSHPort -username $superUser `
					-password $password -download -downloadTo $LogDir -files "/root/$InfinibandNic-status*"
				Copy-RemoteFiles -downloadFrom $ServerVMData.PublicIP -port $ServerVMData.SSHPort -username $superUser `
					-password $password -download -downloadTo $LogDir -files "/root/IMB*"
				Copy-RemoteFiles -downloadFrom $ServerVMData.PublicIP -port $ServerVMData.SSHPort -username $superUser `
					-password $password -download -downloadTo $LogDir -files "/root/kernel-logs-*"
				Copy-RemoteFiles -downloadFrom $ServerVMData.PublicIP -port $ServerVMData.SSHPort -username $superUser `
					-password $password -download -downloadTo $LogDir -files "/root/TestExecution.log"
				Copy-RemoteFiles -downloadFrom $ServerVMData.PublicIP -port $ServerVMData.SSHPort -username $superUser `
					-password $password -download -downloadTo $LogDir -files "/root/state.txt"
				$ConsoleOutput = ( Get-Content -Path "$LogDir\TestExecution.log" | Out-String )
				$FinalStatus = Run-LinuxCmd -ip $ServerVMData.PublicIP -port $ServerVMData.SSHPort -username $superUser `
					-password $password -command "cat /$superUser/state.txt"
				if ($Iteration -eq 1) {
					$TempName = "FirstBoot"
				} else {
					$TempName = "Reboot"
				}
				New-Item -Path "$LogDir\InfiniBand-Verification-$Iteration-$TempName" -Force -ItemType Directory | Out-Null
				Move-Item -Path "$LogDir\$InfinibandNic-status*" -Destination "$LogDir\InfiniBand-Verification-$Iteration-$TempName" | Out-Null
				Move-Item -Path "$LogDir\IMB*" -Destination "$LogDir\InfiniBand-Verification-$Iteration-$TempName" | Out-Null
				Move-Item -Path "$LogDir\kernel-logs-*" -Destination "$LogDir\InfiniBand-Verification-$Iteration-$TempName" | Out-Null
				Move-Item -Path "$LogDir\TestExecution.log" -Destination "$LogDir\InfiniBand-Verification-$Iteration-$TempName" | Out-Null
				Move-Item -Path "$LogDir\state.txt" -Destination "$LogDir\InfiniBand-Verification-$Iteration-$TempName" | Out-Null

				#region Check if $InfinibandNic got IP address
				$logFileName = "$LogDir\InfiniBand-Verification-$Iteration-$TempName\TestExecution.log"
				$pattern = "INFINIBAND_VERIFICATION_SUCCESS_$InfinibandNic"
				Write-LogInfo "Analyzing $logFileName"
				$metaData = "InfiniBand-Verification-$Iteration-$TempName : $InfinibandNic IP"
				$SucessLogs = Select-String -Path $logFileName -Pattern $pattern
				if ($SucessLogs.Count -eq 1) {
					$currentResult = "PASS"
				} else {
					$currentResult = "FAIL"
				}
				Write-LogInfo "$pattern : $currentResult"
				$resultArr += $currentResult
				$CurrentTestResult.TestSummary += New-ResultSummary -testResult $currentResult -metaData $metaData `
					-checkValues "PASS,FAIL,ABORTED" -testName $CurrentTestData.testName
				#endregion

				#region Check ibv_ping_pong tests
				$pattern = "INFINIBAND_VERIFICATION_SUCCESS_IBV_PINGPONG"
				Write-LogInfo "Analyzing $logFileName"
				$metaData = "InfiniBand-Verification-$Iteration-$TempName : IBV_PINGPONG"
				$SucessLogs = Select-String -Path $logFileName -Pattern $pattern
				if ($SucessLogs.Count -eq 1) {
					$currentResult = "PASS"
				} else {
					# Get the actual tests that failed and output them
					$failedPingPongIBV = Select-String -Path $logFileName -Pattern '(_pingpong.*Failed)'
					foreach ($failedTest in $failedPingPongIBV) {
						Write-LogErr "$($failedTest.Line.Split()[-7..-1])"
					}
					$currentResult = "FAIL"
				}
				Write-LogInfo "$pattern : $currentResult"
				$resultArr += $currentResult
				$CurrentTestResult.TestSummary += New-ResultSummary -testResult $currentResult -metaData $metaData `
					-checkValues "PASS,FAIL,ABORTED" -testName $CurrentTestData.testName
				#endregion

				#region Check MPI pingpong intranode tests
				$logFileName = "$LogDir\InfiniBand-Verification-$Iteration-$TempName\TestExecution.log"
				$pattern = "INFINIBAND_VERIFICATION_SUCCESS_MPI1_INTRANODE"
				Write-LogInfo "Analyzing $logFileName"
				$metaData = "InfiniBand-Verification-$Iteration-$TempName : PingPong Intranode"
				$SucessLogs = Select-String -Path $logFileName -Pattern $pattern
				if ($SucessLogs.Count -eq 1) {
					$currentResult = "PASS"
				} else {
					$currentResult = "FAIL"
				}
				Write-LogInfo "$pattern : $currentResult"
				$resultArr += $currentResult
				$CurrentTestResult.TestSummary += New-ResultSummary -testResult $currentResult -metaData $metaData `
					-checkValues "PASS,FAIL,ABORTED" -testName $CurrentTestData.testName
				#endregion

				#region Check MPI1 all nodes tests
				if ($ImbMpiTestIterations -ge 1) {
					$logFileName = "$LogDir\InfiniBand-Verification-$Iteration-$TempName\TestExecution.log"
					$pattern = "INFINIBAND_VERIFICATION_SUCCESS_MPI1_ALLNODES"
					Write-LogInfo "Analyzing $logFileName"
					$metaData = "InfiniBand-Verification-$Iteration-$TempName : IMB-MPI1"
					$SucessLogs = Select-String -Path $logFileName -Pattern $pattern
					if ($SucessLogs.Count -eq 1) {
						$currentResult = "PASS"
					} else {
						$currentResult = "FAIL"
					}
					Write-LogInfo "$pattern : $currentResult"
					$resultArr += $currentResult
					$CurrentTestResult.TestSummary += New-ResultSummary -testResult $currentResult -metaData $metaData `
						-checkValues "PASS,FAIL,ABORTED" -testName $CurrentTestData.testName
				}
				#endregion

				#region Check RMA all nodes tests
				if ($ImbRmaTestIterations -ge 1) {
					$logFileName = "$LogDir\InfiniBand-Verification-$Iteration-$TempName\TestExecution.log"
					$pattern = "INFINIBAND_VERIFICATION_SUCCESS_RMA_ALLNODES"
					Write-LogInfo "Analyzing $logFileName"
					$metaData = "InfiniBand-Verification-$Iteration-$TempName : IMB-RMA"
					$SucessLogs = Select-String -Path $logFileName -Pattern $pattern
					if ($SucessLogs.Count -eq 1) {
						$currentResult = "PASS"
					} else {
						$currentResult = "FAIL"
					}
					Write-LogInfo "$pattern : $currentResult"
					$resultArr += $currentResult
					$CurrentTestResult.TestSummary += New-ResultSummary -testResult $currentResult -metaData $metaData `
						-checkValues "PASS,FAIL,ABORTED" -testName $CurrentTestData.testName
				}
				#endregion

				#region Check NBC all nodes tests
				if ($ImbNbcTestIterations -ge 1) {
					$logFileName = "$LogDir\InfiniBand-Verification-$Iteration-$TempName\TestExecution.log"
					$pattern = "INFINIBAND_VERIFICATION_SUCCESS_NBC_ALLNODES"
					Write-LogInfo "Analyzing $logFileName"
					$metaData = "InfiniBand-Verification-$Iteration-$TempName : IMB-NBC"
					$SucessLogs = Select-String -Path $logFileName -Pattern $pattern
					if ($SucessLogs.Count -eq 1) {
						$currentResult = "PASS"
					} else {
						$currentResult = "FAIL"
					}
					Write-LogInfo "$pattern : $currentResult"
					$resultArr += $currentResult
					$CurrentTestResult.TestSummary += New-ResultSummary -testResult $currentResult -metaData $metaData `
						-checkValues "PASS,FAIL,ABORTED" -testName $CurrentTestData.testName
				}
				#endregion

				if ($FinalStatus -imatch "TestCompleted") {
					Write-LogInfo "Test finished successfully."
					Write-LogInfo $ConsoleOutput
				} else {
					Write-LogErr "Test failed."
					Write-LogErr $ConsoleOutput
				}
				#endregion
			} else {
				$FinalStatus = "TestFailed"
			}

			if ($FinalStatus -imatch "TestFailed") {
				Write-LogErr "Test failed. Last known status : $CurrentStatus."
				$testResult = "FAIL"
			} elseif ($FinalStatus -imatch "TestAborted") {
				Write-LogErr "Test ABORTED. Last known status : $CurrentStatus."
				$testResult = "ABORTED"
			} elseif ($FinalStatus -imatch "TestCompleted") {
				Write-LogInfo "Test Completed. Result : $FinalStatus."
				$testResult = "PASS"
				$TotalSuccessCount += 1
			} elseif ($FinalStatus -imatch "TestRunning") {
				Write-LogInfo "PowerShell background job for test is completed but VM is reporting that test is still running. Please check $LogDir\mdConsoleLogs.txt"
				Write-LogInfo "Contests of state.txt : $FinalStatus"
				$testResult = "FAIL"
			}
			Write-LogInfo "**********************************************"
			if ($RemainingRebootIterations -gt 0) {
				if ($testResult -eq "PASS") {
					$TestProvider.RestartAllDeployments($AllVMData)
					# In some cases, IB will not be initialized after reboot
					Resolve-UninitializedIB
					$RemainingRebootIterations -= 1
				} else {
					Write-LogErr "Stopping the test due to failures."
				}
			}
		}
		while (($ExpectedSuccessCount -ne $Iteration) -and ($testResult -eq "PASS"))

		if ($ExpectedSuccessCount -eq $TotalSuccessCount) {
			$testResult = "PASS"
		} else {
			$testResult = "FAIL"
		}
		Write-LogInfo "Test result : $testResult"
		Write-LogInfo "Test Completed"
	} catch {
		$ErrorMessage =  $_.Exception.Message
		$ErrorLine = $_.InvocationInfo.ScriptLineNumber
		Write-LogErr "EXCEPTION : $ErrorMessage at line: $ErrorLine"
	} finally {
		if (!$testResult) {
			$testResult = "ABORTED"
		}
		$resultArr += $testResult
	}
	$CurrentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
	return $CurrentTestResult
}

Main