##############################################################################################
# TestProvider.psm1
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
# Operations :
#
<#
.SYNOPSIS
	PS modules for LISAv2 test automation
	This module provides the general test operations

.PARAMETER
	<Parameters>

.INPUTS


.NOTES
	Creation Date:
	Purpose/Change:

.EXAMPLE


#>
###############################################################################################


Class TestProvider
{
	[string] $CustomKernel
	[string] $CustomLIS
	[bool]   $ReuseVmOnFailure = $false

	[object] DeployVMs([xml] $GlobalConfig, [object] $SetupTypeData, [object] $TestCaseData, [string] $TestLocation, [string] $RGIdentifier, [bool] $UseExistingRG, [string] $ResourceCleanup) {
		return $null
	}

	[void] RunSetup($VmData, $CurrentTestData, $TestParameters, $ApplyCheckPoint) {}

	[void] RunTestCaseCleanup ($AllVMData, $CurrentTestData, $CurrentTestResult, $CollectVMLogs, $RemoveFiles, $User, $Password, $SetupTypeData, $TestParameters){
		# Remove running background jobs
		Write-LogInfo "Start to do clean up for case $($CurrentTestData.testName)"
		$currentTestBackgroundJobs = Get-Content $global:LogDir\CurrentTestBackgroundJobs.txt -ErrorAction SilentlyContinue
		if ($currentTestBackgroundJobs) {
			$currentTestBackgroundJobs = $currentTestBackgroundJobs.Split()
		}
		foreach ($taskID in $currentTestBackgroundJobs) {
			Write-LogInfo "Removing Background Job $taskID..."
			Remove-Job -Id $taskID -Force
			Remove-Item $global:LogDir\CurrentTestBackgroundJobs.txt -ErrorAction SilentlyContinue
		}

		if ($CollectVMLogs) {
			Get-SystemDetailLogs -AllVMData $AllVMData -User $User -Password $Password
		}
		if ($RemoveFiles) {
			Remove-AllFilesFromHomeDirectory -AllDeployedVMs $AllVMData -User $User -Password $Password
		}
	}

	[void] DeleteTestVMs($allVMData, $SetupTypeData, $UseExistingRG) {}

	[void] RunTestCleanup() {}

	[bool] RestartAllDeployments($allVMData) { return $false }
}



