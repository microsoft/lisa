##############################################################################################
# AzureProvider.psm1
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
# Operations :
#
<#
.SYNOPSIS
	PS modules for LISAv2 test automation
	This module provides the test operations on Azure

.PARAMETER
	<Parameters>

.INPUTS


.NOTES
	Creation Date:
	Purpose/Change:

.EXAMPLE


#>
###############################################################################################
using Module ".\TestProvider.psm1"

Class AzureProvider : TestProvider
{
	[string] $TipSessionId
	[string] $TipCluster

	[object] DeployVMs([xml] $GlobalConfig, [object] $SetupTypeData, [object] $TestCaseData, [string] $TestLocation, [string] $RGIdentifier, [bool] $UseExistingRG, [string] $ResourceCleanup) {
		$allVMData = @()
		$DeploymentElapsedTime = $null
		$ErrorMessage = ""
		try {
			if ($UseExistingRG) {
				Write-LogInfo "Running test against existing resource group: $RGIdentifier"
				$allVMData = Get-AllDeploymentData -ResourceGroups $RGIdentifier
				if (!$allVMData) {
					Write-LogInfo "No VM is found in resource group $RGIdentifier, start to deploy VMs"
				}
			}
			if (!$allVMData) {
				$isAllDeployed = Create-AllResourceGroupDeployments -SetupTypeData $SetupTypeData -TestCaseData $TestCaseData -Distro $RGIdentifier `
					-TestLocation $TestLocation -GlobalConfig $GlobalConfig -TipSessionId $this.TipSessionId -TipCluster $this.TipCluster `
					-UseExistingRG $UseExistingRG -ResourceCleanup $ResourceCleanup

				if ($isAllDeployed[0] -eq "True") {
					$deployedGroups = $isAllDeployed[1]
					$DeploymentElapsedTime = $isAllDeployed[3]
					$allVMData = Get-AllDeploymentData -ResourceGroups $deployedGroups
				} else {
					$ErrorMessage = "One or more deployments failed."
					Write-LogErr $ErrorMessage
					return @{"VmData" = $null; "Error" = $ErrorMessage}
				}
			}
			$isVmAlive = Is-VmAlive -AllVMDataObject $allVMData
			if ($isVmAlive -eq "True") {
				if ((Test-Path -Path  .\Extras\UploadDeploymentDataToDB.ps1) -and !$UseExistingRG) {
					$null = .\Extras\UploadDeploymentDataToDB.ps1 -allVMData $allVMData -DeploymentTime $DeploymentElapsedTime.TotalSeconds
				}

				$enableSRIOV = $TestCaseData.AdditionalHWConfig.Networking -imatch "SRIOV"
				$customStatus = Set-CustomConfigInVMs -CustomKernel $this.CustomKernel -CustomLIS $this.CustomLIS -EnableSRIOV $enableSRIOV `
					-AllVMData $allVMData -TestProvider $this
				if (!$customStatus) {
					$ErrorMessage = "Failed to set custom config in VMs."
					Write-LogErr $ErrorMessage
					return @{"VmData" = $null; "Error" = $ErrorMessage}
				}
			}
			else {
				Write-LogErr "Unable to connect SSH ports.."
			}
		} catch {
			Write-LogErr "Exception detected. Source : DeployVMs()"
			$line = $_.InvocationInfo.ScriptLineNumber
			$script_name = ($_.InvocationInfo.ScriptName).Replace($PWD, ".")
			$ErrorMessage = $_.Exception.Message
			Write-LogErr "EXCEPTION : $ErrorMessage"
			Write-LogErr "Source : Line $line in script $script_name."
		}
		return @{"VmData" = $allVMData; "Error" = $ErrorMessage}
	}

	[void] DeleteTestVMs($allVMData, $SetupTypeData, $UseExistingRG) {
		$rgs = @()
		foreach ($vmData in $AllVMData) {
			$rgs += $vmData.ResourceGroupName
		}
		$uniqueRgs = $rgs | Select-Object -Unique
		foreach ($rg in $uniqueRgs) {
			$isCleaned = Delete-ResourceGroup -RGName $rg -UseExistingRG $UseExistingRG
			if (!$isCleaned)
			{
				Write-LogInfo "Failed to trigger delete resource group $rg.. Please delete it manually."
			}
			else
			{
				Write-LogInfo "Successfully cleaned up RG ${rg}.."
			}
		}
	}

	[bool] RestartAllDeployments($AllVMData) {
		$restartJobs = @()
		foreach ( $vmData in $AllVMData ) {
			Write-LogInfo "Triggering Restart-$($vmData.RoleName)..."
			$restartJobs += Restart-AzureRmVM -ResourceGroupName $vmData.ResourceGroupName -Name $vmData.RoleName -Verbose -AsJob
		}
		$recheckAgain = $true
		Write-LogInfo "Waiting until VMs restart..."
		$jobCount = $restartJobs.Count
		$completedJobsCount = 0
		while ($recheckAgain) {
			$recheckAgain = $false
			$tempJobs = @()
			foreach ($restartJob in $restartJobs) {
				if ($restartJob.State -eq "Completed") {
					$completedJobsCount += 1
					Write-LogInfo "[$completedJobsCount/$jobCount] $($restartJob.Name) is done."
					$null = Remove-Job -Id $restartJob.ID -Force -ErrorAction SilentlyContinue
				} elseif ($restartJob.State -eq "Failed") {
					$jobError = Get-Job -Name $restartJob.Name | Receive-Job 2>&1
					Write-LogErr "$($restartJob.Name) failed with error: ${jobError}"
					return $false
				} else {
					$tempJobs += $restartJob
					$recheckAgain = $true
				}
			}
			$restartJobs = $tempJobs
			Start-Sleep -Seconds 1
		}
		if ((Is-VmAlive -AllVMDataObject $AllVMData) -eq "True") {
			return $true
		}
		return $false
	}
}