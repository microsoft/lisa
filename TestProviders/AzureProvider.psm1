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
	[bool] $EnableTelemetry
	[string] $PlatformFaultDomainCount
	[string] $PlatformUpdateDomainCount

	[object] DeployVMs([xml] $GlobalConfig, [object] $SetupTypeData, [object] $TestCaseData, [string] $TestLocation, [string] $RGIdentifier, [bool] $UseExistingRG, [string] $ResourceCleanup) {
		$allVMData = @()
		$DeploymentElapsedTime = $null
		$ErrorMessage = ""
		try {
			if ($UseExistingRG) {
				Write-LogInfo "Running test against existing resource group: $RGIdentifier"
				$allVMData = Get-AllDeploymentData -ResourceGroups $RGIdentifier
				Add-DefaultTagsToResourceGroup -ResourceGroup $RGIdentifier -CurrentTestData $TestCaseData
				if (!$allVMData) {
					Write-LogInfo "No VM is found in resource group $RGIdentifier, start to deploy VMs"
				}
			}
			if (!$allVMData) {
				$isAllDeployed = Create-AllResourceGroupDeployments -SetupTypeData $SetupTypeData -TestCaseData $TestCaseData -Distro $RGIdentifier `
					-TestLocation $TestLocation -GlobalConfig $GlobalConfig -TipSessionId $this.TipSessionId -TipCluster $this.TipCluster `
					-UseExistingRG $UseExistingRG -ResourceCleanup $ResourceCleanup -PlatformFaultDomainCount $this.PlatformFaultDomainCount `
					-PlatformUpdateDomainCount $this.PlatformUpdateDomainCount

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
				if (($this.EnableTelemetry -and !$UseExistingRG)) {
					$null = Upload-AzureBootAndDeploymentDataToDB -allVMData $allVMData -DeploymentTime $DeploymentElapsedTime.TotalSeconds -CurrentTestData $TestCaseData
				} else {
					Write-LogInfo "Skipping boot data telemetry collection."
				}

				$enableSRIOV = $TestCaseData.AdditionalHWConfig.Networking -imatch "SRIOV"
				if (!$global:IsWindowsImage) {
					$customStatus = Set-CustomConfigInVMs -CustomKernel $this.CustomKernel -CustomLIS $this.CustomLIS -EnableSRIOV $enableSRIOV `
						-AllVMData $allVMData -TestProvider $this
					if (!$customStatus) {
						$ErrorMessage = "Failed to set custom config in VMs."
						Write-LogErr $ErrorMessage
						return @{"VmData" = $null; "Error" = $ErrorMessage}
					}
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

	[void] DeleteVMs($allVMData, $SetupTypeData, $UseExistingRG) {
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
				Write-LogInfo "Successfully started clean up for RG ${rg}.."
			}
		}
	}

	[bool] RestartAllDeployments($AllVMData) {
		$VMCoresArray = @()
		$AzureVMSizeInfo = Get-AzVMSize -Location $AllVMData[0].Location
		foreach ( $vmData in $AllVMData ) {
			if (Restart-VMFromShell -VMData $vmData -SkipRestartCheck) {
				Write-Loginfo "Restart-VMFromShell executes successfully."
			} else {
				Write-LogErr "Restart-VMFromShell executes failed."
				return $false
			}
			$VMCoresArray += ($AzureVMSizeInfo | Where-Object { $_.Name -eq $vmData.InstanceSize }).NumberOfCores
		}
		$MaximumCores = ($VMCoresArray | Measure-Object -Maximum).Maximum

		# Calculate timeout depending on VM size.
		# We're adding timeout of 10 minutes (default timeout) + 1 minute/10 cores (additional timeout).
		# So For D64 VM, timeout = 10 + int[64/10] = 16 minutes.
		# M128 VM, timeout = 10 + int[128/10] = 23 minutes.
		$Timeout = New-Timespan -Minutes ([int]($MaximumCores / 10) + 10)
		$sw = [diagnostics.stopwatch]::StartNew()
		foreach ($vmData in $AllVMData) {
			$vm = Get-AzVM -ResourceGroupName $vmData.ResourceGroupName -Name $vmData.RoleName -Status
			while (($vm.Statuses[-1].Code -ne "PowerState/running") -and ($sw.elapsed -lt $Timeout)) {
				Write-LogInfo "VM $($vmData.RoleName) is in $($vm.Statuses[-1].Code) state, still not in running state"
				$vm = Get-AzVM -ResourceGroupName $vmData.ResourceGroupName -Name $vmData.RoleName -Status
			}
		}

		if ((Is-VmAlive -AllVMDataObject $AllVMData) -eq "True") {
			return $true
		}
		return $false
	}

	[void] RunTestCleanup() {
		# Wait till all the cleanup background jobs successfully started cleanup of resource groups.
		$DeleteResourceGroupJobs = Get-Job | Where-Object { $_.Name -imatch "DeleteResourceGroup" }
		$RunningJobs = $DeleteResourceGroupJobs | Where-Object { $_.State -imatch "Running" }
		While ( $RunningJobs ) {
			$RunningJobs | ForEach-Object {
				Write-LogInfo "$($_.Name) background job is running. Waiting to finish..."
			}
			Start-Sleep -Seconds 5
			$RunningJobs = $DeleteResourceGroupJobs | Where-Object { $_.State -imatch "Running" }
		}
		if ($DeleteResourceGroupJobs) {
			Write-LogInfo "*****************Background clenaup job logs*****************"
			$DeleteResourceGroupJobs | Receive-Job
			Write-LogInfo "*************************************************************"
			$DeleteResourceGroupJobs | Remove-Job -Force
		}
	}
}
