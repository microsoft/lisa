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

	[object] DeployVMs([xml] $GlobalConfig, [object] $SetupTypeData, [object] $TestCaseData, [string] $TestLocation, [string] $RGIdentifier, [bool] $UseExistingRG, [string] $ResourceCleanup, [switch] $EnableTelemetry) {
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
					$ErrorMessage = "One or more deployments failed. " + $isAllDeployed[4]
					Write-LogErr $ErrorMessage
					return @{"VmData" = $null; "Error" = $ErrorMessage}
				}
			}
			$isVmAlive = Is-VmAlive -AllVMDataObject $allVMData
			if ($isVmAlive -eq "True") {
				if (($EnableTelemetry -and !$UseExistingRG)) {
					$null = Upload-AzureBootAndDeploymentDataToDB -allVMData $allVMData -DeploymentTime $DeploymentElapsedTime.TotalSeconds -CurrentTestData $TestCaseData
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
		$ShellRestart = 0
		$VMCoresArray = @()
		Function Start-RestartAzureVMJob ($ResourceGroupName, $RoleName) {
			Write-LogInfo "Triggering Restart-$($RoleName)..."
			$Job = Restart-AzVM -ResourceGroupName $ResourceGroupName -Name $RoleName -AsJob
			$Job.Name = "Restart-$($ResourceGroupName):$($RoleName)"
			return $Job
		}
		$AzureVMSizeInfo = Get-AzVMSize -Location $AllVMData[0].Location
		foreach ( $vmData in $AllVMData ) {
			$restartJobs += Start-RestartAzureVMJob -ResourceGroupName $vmData.ResourceGroupName -RoleName $vmData.RoleName
			$VMCoresArray += ($AzureVMSizeInfo | Where-Object { $_.Name -eq $vmData.InstanceSize }).NumberOfCores
		}
		$MaximumCores = ($VMCoresArray | Measure-Object -Maximum).Maximum

		# Calculate timeout depending on VM size.
		# We're adding timeout of 10 minutes (default timeout) + 1 minute/10 cores (additional timeout).
		# So For D64 VM, timeout = 10 + int[64/10] = 16 minutes.
		# M128 VM, timeout = 10 + int[128/10] = 23 minutes.
		$TimeoutMinutes = [int]($MaximumCores / 10) + 10
		$recheckAgain = $true

		# Timeout check is started after all the restart operations are triggered.
		$Timeout = (Get-Date).AddMinutes($TimeoutMinutes)
		Write-LogInfo "Waiting until VMs restart (Timeout = $TimeoutMinutes minutes)..."
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
					if ((Get-Date) -gt $Timeout ) {
						Write-LogErr "$($restartJob.Name) timed out after $TimeoutMinutes minutes. Removing the job."
						$null = Remove-Job -Id $restartJob.ID -Force -ErrorAction SilentlyContinue
						$TimedOutResourceGroup = $restartJob.Name.Replace("Restart-",'').Split(':')[0]
						$TimedOutRoleName = $restartJob.Name.Replace("Restart-",'').Split(':')[1]
						$TimedOutVM = $AllVMData | Where-Object {$_.ResourceGroupName -eq $TimedOutResourceGroup -and $_.RoleName -eq $TimedOutRoleName}
						$Null = Restart-VMFromShell -VMData $TimedOutVM -SkipRestartCheck
						$ShellRestart += 1
					} else {
						$tempJobs += $restartJob
						$recheckAgain = $true
					}
				}
			}
			$restartJobs = $tempJobs
			Start-Sleep -Seconds 1
		}
		if ($ShellRestart -gt 0) {
			Write-LogInfo "$ShellRestart VMs were restarted from shell. Sleeping 5 seconds..."
			Start-Sleep -Seconds 5
		}
		if ((Is-VmAlive -AllVMDataObject $AllVMData) -eq "True") {
			return $true
		}
		return $false
	}
}
