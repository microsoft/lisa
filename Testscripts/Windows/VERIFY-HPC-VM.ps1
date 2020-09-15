# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
<#
.Synopsis
	

.Description
	
#>

param([object] $AllVmData, [string]$TestParams)

function Main {
	param($AllVMData, $TestParams)
	$currentTestResult = Create-TestResultObject
	try {
		$testResult = $resultFail
		
		#region Generate constants.sh
		Write-LogInfo "Generating constants.sh ..."
		$constantsFile = "$LogDir\constants.sh"
		foreach ($TestParam in $CurrentTestData.TestParameters.param) {
			Add-Content -Value "$TestParam" -Path $constantsFile
			Write-LogInfo "$TestParam added to constants.sh"
		}
		Write-LogInfo "constants.sh created successfully..."
		#endregion

		# Getting queue counts and interrupt counts after resuming.
		$vfname = Run-LinuxCmd -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password -command "bash /home/$user/getvf.sh" -runAsSudo
		if ($vfname -ne '') {
			$tx_queue_count2 = Run-LinuxCmd -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password -command "ethtool -l ${vfname} | grep -i tx | tail -n 1 | cut -d ':' -f 2 | tr -d '[:space:]'" -runAsSudo
			$interrupt_count2 = Run-LinuxCmd -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password -command "cat /proc/interrupts | grep -i mlx | grep -i msi | wc -l" -runAsSudo
		}
		if ($tx_queue_count1 -ne $tx_queue_count2) {
			Write-LogErr "Before hibernation, Tx queue count - $tx_queue_count1. After waking up, Tx queue count - $tx_queue_count2"
			throw "Tx queue counts changed after waking up."
		} else {
			Write-LogInfo "Successfully verified Tx queue count matching in Current hardware settings."
		}

		if ($interrupt_count1 -ne $interrupt_count2) {
			Write-LogErr "Before hibernation, MSI interrupts of mlx driver - $interrupt_count1. After waking up, MSI interrupts of mlx driver - $interrupt_count2"
			throw "MSI interrupt counts changed after waking up."
		} else {
			Write-LogInfo "Successfully verified MSI interrupt counts matching"
		}

		$testResult = $resultPass
		Copy-RemoteFiles -downloadFrom $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password -download -downloadTo $LogDir -files "*.log" -runAsSudo
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