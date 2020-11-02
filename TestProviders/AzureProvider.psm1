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

Class AzureProvider : TestProvider {
	[bool] $RunWithTiP = $false
	[bool] $EnableTelemetry
	[string] $PlatformFaultDomainCount
	[string] $PlatformUpdateDomainCount
	# Whether or not to add NetworkSecurityGroup and NSG rules to Microsoft.Network/networkInterfaces resources
	# XML/Other/NetworkSecurityGroupRules.xml need to be prepared.
	[bool] $EnableNSG = $false

	[object] DeployVMs([xml] $GlobalConfig, [object] $SetupTypeData, [object] $TestCaseData, [string] $TestLocation, [string] $RGIdentifier, [bool] $UseExistingRG, [string] $ResourceCleanup) {
		if ($this.RunWithTiP) {
			$UseExistingRG = $true
		}
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
				else {
					Add-DefaultTagsToResourceGroup -ResourceGroup $RGIdentifier -CurrentTestData $TestCaseData
				}
			}
			if (!$allVMData) {
				$isAllDeployed = Invoke-AllResourceGroupDeployments -SetupTypeData $SetupTypeData -CurrentTestData $TestCaseData -RGIdentifier $RGIdentifier `
					-TestLocation $TestCaseData.SetupConfig.TestLocation -UseExistingRG $UseExistingRG -ResourceCleanup $ResourceCleanup -EnableNSG $this.EnableNSG

				if ($isAllDeployed[0] -eq "True") {
					$deployedGroups = $isAllDeployed[1]
					$DeploymentElapsedTime = $isAllDeployed[3]
					$allVMData = Get-AllDeploymentData -ResourceGroups $deployedGroups
					# After each successful deployment, update the $global:detectedDistro for reference by other scripts and logic
					if ($TestCaseData.SetupConfig.OSType -notcontains "Windows") {
						$null = Detect-LinuxDistro -VIP $allVMData[0].PublicIP -SSHport $allVMData[0].SSHPort -testVMUser $global:user -testVMPassword $global:password
					}
				}
				else {
					$ErrorMessage = "One or more deployments failed. " + $isAllDeployed[4]
					Write-LogErr $ErrorMessage
					return @{"VmData" = $allVMData; "Error" = $ErrorMessage }
				}
			}
			$isVmAlive = Is-VmAlive -AllVMDataObject $allVMData
			if ($isVmAlive -eq "True") {
				if (($this.EnableTelemetry -and !$UseExistingRG)) {
					$null = Upload-AzureBootAndDeploymentDataToDB -allVMData $allVMData -DeploymentTime $DeploymentElapsedTime.TotalSeconds -CurrentTestData $TestCaseData
				}
				else {
					Write-LogInfo "Skipping boot data telemetry collection."
				}

				$enableSRIOV = $TestCaseData.SetupConfig.Networking -imatch "SRIOV"
				if ($TestCaseData.SetupConfig.OSType -notcontains "Windows") {
					$customStatus = Set-CustomConfigInVMs -CustomKernel $this.CustomKernel -CustomLIS $this.CustomLIS -EnableSRIOV $enableSRIOV `
						-AllVMData $allVMData -TestProvider $this
					if (!$customStatus) {
						$ErrorMessage = "Failed to set custom config: -CustomKernel [$($this.CustomKernel)] -CustomLIS [$($this.CustomLIS)] -EnableSRIOV [$enableSRIOV] in VMs."
						Write-LogErr $ErrorMessage
						return @{"VmData" = $allVMData; "Error" = $ErrorMessage }
					}
				}
			}
			else {
				# Do not DeleteVMs here, instead, we will set below $ErrorMessage
				#, to indicate there's deployment errors, and TestController will handle those errors
				$ErrorMessage = "Unable to connect to deployed VMs..."
				Write-LogErr $ErrorMessage
				return @{"VmData" = $allVMData; "Error" = $ErrorMessage }
			}
		}
		catch {
			Write-LogErr "Exception detected. Source : DeployVMs()"
			$line = $_.InvocationInfo.ScriptLineNumber
			$script_name = ($_.InvocationInfo.ScriptName).Replace($PWD, ".")
			$ErrorMessage = $_.Exception.Message
			Write-LogErr "EXCEPTION : $ErrorMessage"
			Write-LogErr "Source : Line $line in script $script_name."
		}
		return @{"VmData" = $allVMData; "Error" = $ErrorMessage }
	}

	[void] DeleteVMs($allVMData, $SetupTypeData, $UseExistingRG) {
		if ($this.RunWithTiP) {
			$UseExistingRG = $true
		}
		$rgs = @()
		foreach ($vmData in $allVMData) {
			$rgs += $vmData.ResourceGroupName
		}
		$uniqueRgs = $rgs | Select-Object -Unique
		foreach ($rg in $uniqueRgs) {
			$null = Delete-ResourceGroup -RGName $rg -UseExistingRG $UseExistingRG
		}
	}

	[bool] RestartAllDeployments($AllVMData) {
		$VMCoresArray = @()
		$AzureVMSizeInfo = Get-AzVMSize -Location $AllVMData[0].Location
		foreach ( $vmData in $AllVMData ) {
			if (Restart-VMFromShell -VMData $vmData -SkipRestartCheck) {
				Write-Loginfo "Restart-VMFromShell executes successfully."
			}
			else {
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
		$vmStatus = $null
		foreach ($vmData in $AllVMData) {
			$vmStatus = Get-AzVM -ResourceGroupName $vmData.ResourceGroupName -Name $vmData.RoleName -Status
			while (($vmStatus.Statuses[-1].Code -ne "PowerState/running") -and ($sw.elapsed -lt $Timeout)) {
				Write-LogInfo "VM $($vmData.RoleName) is in $($vmStatus.Statuses[-1].Code) state, still not in running state"
				Start-Sleep -Seconds 10
				$vmStatus = Get-AzVM -ResourceGroupName $vmData.ResourceGroupName -Name $vmData.RoleName -Status
			}
		}

		if ($vmStatus -and $vmStatus.Statuses[-1].Code -eq "PowerState/running") {
			if ((Is-VmAlive -AllVMDataObject $AllVMData -MaxRetryCount 100) -eq "True") {
				return $true
			}
		}
		return $false
	}

	[void] RunTestCaseCleanup ($AllVMData, $CurrentTestData, $CurrentTestResult, $CollectVMLogs, $RemoveFiles, $User, $Password, $SetupTypeData, $TestParameters) {
		try {
			if ($CurrentTestData.CleanupScript) {
				foreach ($vmData in $AllVMData) {
					foreach ($script in $($CurrentTestData.CleanupScript).Split(",")) {
						$null = Run-SetupScript -Script $script -Parameters $TestParameters -VMData $vmData -CurrentTestData $CurrentTestData -TestProvider $this
					}
				}
			}
			([TestProvider]$this).RunTestCaseCleanup($AllVMData, $CurrentTestData, $CurrentTestResult, $CollectVMLogs, $RemoveFiles, $User, $Password, $SetupTypeData, $TestParameters)
		}
		catch {
			$ErrorMessage = $_.Exception.Message
			Write-Output "EXCEPTION in RunTestCaseCleanup : $ErrorMessage"
		}
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
		# Clean up AzContext only when using service principal or using AzureContextFile
		$spClientID = $global:XmlSecrets.secrets.SubscriptionServicePrincipalClientID
		$spKey = $global:XmlSecrets.secrets.SubscriptionServicePrincipalKey
		$contextFilePath = $global:XmlSecrets.secrets.AzureContextFilePath
		if (($spClientID -and $spKey) -or $contextFilePath) {
			Clear-AzContext -Force -ErrorAction SilentlyContinue | Out-NULL
		}
		# Remove ppk file if exist
		Remove-Item "$env:TEMP\*.ppk" -Force -ErrorAction SilentlyContinue
	}
}
