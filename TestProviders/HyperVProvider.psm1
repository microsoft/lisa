##############################################################################################
# HyperVProvider.psm1
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
# Operations :
#
<#
.SYNOPSIS
	PS modules for LISAv2 test automation
	This module provides the test operations on HyperV

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

Class HyperVProvider : TestProvider
{
	[string] $VMGeneration
	[string] $BaseCheckpoint = "ICAbase"
	[bool]   $ReuseVmOnFailure = $true

	[object] DeployVMs([xml] $GlobalConfig, [object] $SetupTypeData, [object] $TestCaseData, [string] $TestLocation, [string] $RGIdentifier, [bool] $UseExistingRG, [string] $ResourceCleanup) {
		$allVMData = @()
		$DeploymentElapsedTime = $null
		try {
			if ($UseExistingRG) {
				Write-LogInfo "Running test against existing HyperV group: $RGIdentifier"
				$allVMData = Get-AllHyperVDeployementData -HyperVGroupNames $RGIdentifier -GlobalConfig $GlobalConfig
				if (!$allVMData) {
					Write-LogInfo "No VM is found in HyperV group $RGIdentifier, start to deploy VMs"
				}
			}
			if (!$allVMData) {
				$isAllDeployed = Create-AllHyperVGroupDeployments -SetupTypeData $SetupTypeData -GlobalConfig $GlobalConfig -TestLocation $TestLocation `
				-Distro $RGIdentifier -VMGeneration $this.VMGeneration -TestCaseData $TestCaseData -UseExistingRG $UseExistingRG

				if ($isAllDeployed[0] -eq "True") {
					$DeployedHyperVGroup = $isAllDeployed[1]
					$DeploymentElapsedTime = $isAllDeployed[3]
					$allVMData = Get-AllHyperVDeployementData -HyperVGroupNames $DeployedHyperVGroup -GlobalConfig $GlobalConfig
				}
				else {
					Write-LogErr "One or More Deployments are Failed..!"
					return $null
				}
			}

			$isVmAlive = Is-VmAlive -AllVMDataObject $allVMData
			if ($isVmAlive -eq "True") {
				$customStatus = Set-CustomConfigInVMs -CustomKernel $this.CustomKernel -CustomLIS $this.CustomLIS `
					-AllVMData $allVMData -TestProvider $this -RegisterRhelSubscription
				if (!$customStatus) {
					Write-LogErr "Failed to set custom config in VMs, abort the test"
					return $null
				}

				Inject-HostnamesInHyperVVMs -allVMData $allVMData
				Create-HyperVCheckpoint -VMData $AllVMData -CheckpointName $this.BaseCheckpoint -TurnOff $false

				if ((Test-Path -Path  .\Extras\UploadDeploymentDataToDB.ps1) -and !$UseExistingRG) {
					.\Extras\UploadDeploymentDataToDB.ps1 -allVMData $allVMData -DeploymentTime $DeploymentElapsedTime.TotalSeconds
				}

			} else {
				Write-LogErr "Unable to connect SSH ports.."
			}

			# Note(v-advlad): clustered vms will not be cleaned up
			# Todo: clean up clustered vms that do not belong to a Hyper-V group
			if ($SetupTypeData.ClusteredVM) {
				foreach ($VM in $allVMData) {
					Remove-VMGroupMember -Name $VM.HyperVGroupName -VM $(Get-VM -name $VM.RoleName -ComputerName $VM.HyperVHost)
				}
			}
		} catch {
			Write-LogErr "Exception detected. Source : DeployVMs()"
			$line = $_.InvocationInfo.ScriptLineNumber
			$script_name = ($_.InvocationInfo.ScriptName).Replace($PWD,".")
			$ErrorMessage =  $_.Exception.Message
			Write-LogErr "EXCEPTION : $ErrorMessage"
			Write-LogErr "Source : Line $line in script $script_name."
		}

		# Note(v-advlad): Dependency VMs need to be removed
		$allVMData = Check-IP -VMData $allVMData
		return $allVMData
	}

	[void] RunSetup($VmData, $CurrentTestData, $TestParameters, $ApplyCheckPoint) {
		if ($ApplyCheckPoint) {
			Apply-HyperVCheckpoint -VMData $VmData -CheckpointName $this.BaseCheckpoint
			$VmData = Check-IP -VMData $VmData
			Write-LogInfo "Public IP found for all VMs in deployment after checkpoint restore"
		}

		if ($CurrentTestData.SetupScript) {
			if ($null -eq $CurrentTestData.runSetupScriptOnlyOnce) {
				foreach ($VM in $VmData) {
					if (Get-VM -Name $VM.RoleName -ComputerName $VM.HyperVHost -EA SilentlyContinue) {
						Stop-VM -Name $VM.RoleName -TurnOff -Force -ComputerName $VM.HyperVHost
					}
					foreach ($script in $($CurrentTestData.SetupScript).Split(",")) {
						$null = Run-SetupScript -Script $script -Parameters $TestParameters -VMData $VM -CurrentTestData $CurrentTestData
					}
					if (Get-VM -Name $VM.RoleName -ComputerName $VM.HyperVHost -EA SilentlyContinue) {
						Start-VM -Name $VM.RoleName -ComputerName $VM.HyperVHost -EA Stop
					}
				}
			}
			else {
				foreach ($script in $($CurrentTestData.SetupScript).Split(",")) {
					$null = Run-SetupScript -Script $script -Parameters $TestParameters -VMData $VmData -CurrentTestData $CurrentTestData
				}
			}
		}
	}

	[void] RunTestCaseCleanup ($AllVMData, $CurrentTestData, $CurrentTestResult, $CollectVMLogs, $RemoveFiles, $User, $Password, $SetupTypeData, $TestParameters){
		try
		{
			if ($CurrentTestData.CleanupScript) {
				foreach ($VM in $AllVMData) {
					if (Get-VM -Name $VM.RoleName -ComputerName `
						$VM.HyperVHost -EA SilentlyContinue) {
						Stop-VM -Name $VM.RoleName -TurnOff -Force -ComputerName `
							$VM.HyperVHost
					}
					foreach ($script in $($CurrentTestData.CleanupScript).Split(",")) {
						$null = Run-SetupScript -Script $script -Parameters $TestParameters -VMData $VM -CurrentTestData $CurrentTestData
					}
					if (Get-VM -Name $VM.RoleName -ComputerName $VM.HyperVHost `
						-EA SilentlyContinue) {
						Start-VM -Name $VM.RoleName -ComputerName `
							$VM.HyperVHost
					}
				}
			}

			if ($SetupTypeData.ClusteredVM) {
				foreach ($VM in $AllVMData) {
					Add-VMGroupMember -Name $VM.HyperVGroupName -VM (Get-VM -name $VM.RoleName -ComputerName $VM.HyperVHost) `
						-ComputerName $VM.HyperVHost
				}
			}

			([TestProvider]$this).RunTestCaseCleanup($AllVMData, $CurrentTestData, $CurrentTestResult, $CollectVMLogs, $RemoveFiles, $User, $Password, $SetupTypeData, $TestParameters)
			if ($CurrentTestResult.TestResult -ne "PASS") {
				Create-HyperVCheckpoint -VMData $AllVMData -CheckpointName "$($CurrentTestData.TestName)-$($CurrentTestResult.TestResult)" `
					-ShouldTurnOffVMBeforeCheckpoint $false -ShouldTurnOnVMAfterCheckpoint $false
			}
		}
		catch
		{
			$ErrorMessage =  $_.Exception.Message
			Write-Output "EXCEPTION in RunTestCaseCleanup : $ErrorMessage"
		}
	}

	[void] DeleteTestVMs($allVMData, $SetupTypeData, $UseExistingRG) {
		foreach ($vmData in $AllVMData) {
			$isCleaned = Delete-HyperVGroup -HyperVGroupName $vmData.HyperVGroupName `
				-HyperVHost $vmData.HyperVHost -SetupTypeData $SetupTypeData -UseExistingRG $UseExistingRG
			if (Get-Variable 'DependencyVmHost' -Scope 'Global' -EA 'Ig') {
				if ($global:DependencyVmHost -ne $vmData.HyperVHost) {
					$isDepCleaned = Delete-HyperVGroup -HyperVGroupName $vmData.HyperVGroupName `
						-HyperVHost $global:DependencyVmHost -SetupTypeData $SetupTypeData `
						-UseExistingRG $UseExistingRG
					$isCleaned = $isCleaned -and $isDepCleaned
				}
			}

			if (!$isCleaned) {
				Write-LogInfo "Failed to delete HyperV group $($vmData.HyperVGroupName). Please delete it manually."
			} elseif (!$UseExistingRG) {
				Write-LogInfo "Successfully delete HyperV group $($vmData.HyperVGroupName)."
			}
		}
	}

	[bool] RestartAllDeployments($allVMData) {
		foreach ( $VM in $allVMData )
		{
			Stop-HyperVGroupVMs -HyperVGroupName $VM.HyperVGroupName -HyperVHost $VM.HyperVHost
		}
		foreach ( $VM in $allVMData )
		{
			Start-HyperVGroupVMs -HyperVGroupName $VM.HyperVGroupName -HyperVHost $VM.HyperVHost
		}
		if ((Is-VmAlive -AllVMDataObject $AllVMData) -eq "True") {
			return $true
		}
		return $false
	}

	[void] RunTestCleanup() {
		# $OsVhdDownloaded is set to global variable in HyperV.psm1 in
		# Create-HyperVGroupDeployment(), if VHD is downloaded from external (web) source.
		# It's value will be path of downloaded VHD file.
		if ($Global:OsVhdDownloaded) {
			Write-LogInfo "Removing downloaded OsVHD: $Global:OsVhdDownloaded"
			[void](Remove-Item -Path $Global:OsVhdDownloaded -Force -ErrorAction SilentlyContinue)
		}
	}
}