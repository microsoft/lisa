# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
<#
.Synopsis
Check the VM has proper IB driver setup.

.Description
This test verified the HPC has IB over ND or SR-IOV.
For general purpose VMs, this VM will abort.
This script uses the function call, is_hpc_vm from utils.sh.
This functions returns 0, if VM is IB over ND.
Return 1, if VM is IB over SR-IOV.
Return 2, if VM is non HPC VM.
Return 3, if unknown.

TODO: post-LIS installation in ND-based VM

#>

param([object] $AllVmData, [string]$TestParams)

function Main {
	param($AllVMData, $TestParams)
	try {
		Copy-RemoteFiles -uploadTo $AllVMData.PublicIP -port $AllVMData.SSHPort -files $currentTestData.files -username $user -password $password -upload
		Start-Sleep -Seconds 3
		$result = Run-LinuxCmd -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password -command "bash ./check_IB_SRIOV.sh" -runAsSudo
		Write-LogDbg "$result"
		$result = Run-LinuxCmd -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password -command "cat state.txt" -runAsSudo
		Write-LogDbg "$result"
		if ($result -eq "TestCompleted") {
			Write-LogInfo "Verified HPC driver and its requirement in the VM"
			$testResult = $resultPass
		}
		Copy-RemoteFiles -downloadFrom $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password -download -downloadTo $LogDir -files "*.log"
	} catch {
		$ErrorMessage =  $_.Exception.Message
		$ErrorLine = $_.InvocationInfo.ScriptLineNumber
		Write-LogErr "EXCEPTION : $ErrorMessage at line: $ErrorLine"
	} finally {
		if (!$testResult) {
			$testResult = $resultAborted
		}
	}

	return $testResult
}

Main -AllVmData $AllVmData -CurrentTestData $CurrentTestData