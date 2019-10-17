##############################################################################################
# ReadyProvider.psm1
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
# Operations :
#
<#
.SYNOPSIS
	PS modules for LISAv2 test automation
	This module provides the test operations for given Linux machines

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

Class ReadyProvider : TestProvider
{
	[object] DeployVMs([xml] $GlobalConfig, [object] $SetupTypeData, [object] $TestCaseData, [string] $TestLocation, [string] $RGIdentifier, [bool] $UseExistingRG, [string] $ResourceCleanup) {
		function Create-QuickVMNode() {
			$objNode = New-Object -TypeName PSObject
			Add-Member -InputObject $objNode -MemberType NoteProperty -Name PublicIP -Value $null -Force
			Add-Member -InputObject $objNode -MemberType NoteProperty -Name SSHPort -Value $null -Force
			Add-Member -InputObject $objNode -MemberType NoteProperty -Name UserName -Value $null -Force
			Add-Member -InputObject $objNode -MemberType NoteProperty -Name Password -Value $null -Force
			Add-Member -InputObject $objNode -MemberType NoteProperty -Name RoleName -Value $null -Force
			return $objNode
		}

		$allVMData = @()
		$ErrorMessage = ""
		try {
			$allVmList = $RGIdentifier.Split(";");
			$vmIndex = 0
			foreach($vmInfo in $allVmList){
				$vmIndex++
				$vmNode = Create-QuickVMNode

				$vmNode.PublicIP = $vmInfo.Split(":")[0]
				$vmNode.SSHPort = $vmInfo.Split(":")[1]
				$vmNode.UserName = $Global:user
				$vmNode.Password = $Global:password
				$vmNode.RoleName = "Role$vmIndex"
				$allVMData += $vmNode;
			}
			Write-LogInfo("No need to deploy new VM as this test case is running against a prepared environment.")

			$isVmAlive = Is-VmAlive -AllVMDataObject $allVMData
			if ($isVmAlive -ne "True") {
				Write-LogErr "Unable to connect SSH ports.."
			}
		} catch {
			Write-LogErr "Exception detected. Source : DeployVMs()"
			$line = $_.InvocationInfo.ScriptLineNumber
			$script_name = ($_.InvocationInfo.ScriptName).Replace($PWD,".")
			$ErrorMessage =  $_.Exception.Message
			Write-LogErr "EXCEPTION : $ErrorMessage"
			Write-LogErr "Source : Line $line in script $script_name."
		}

		return @{"VmData" = $allVMData; "Error" = $ErrorMessage}
	}

	[void] DeleteVMs($allVMData, $SetupTypeData, $UseExistingRG) {
		Write-LogInfo("Will not remove any VM as this test case is running against a prepared environment.")
	}

	[void] RunSetup($VmData, $CurrentTestData, $TestParameters, $ApplyCheckPoint) {
		if ($CurrentTestData.SetupScript) {
			if ($null -eq $CurrentTestData.runSetupScriptOnlyOnce) {
				foreach ($VM in $VmData) {
					foreach ($script in $($CurrentTestData.SetupScript).Split(",")) {
						$null = Run-SetupScript -Script $script -Parameters $TestParameters -VMData $VM -CurrentTestData $CurrentTestData
					}
				}
			} else {
				foreach ($script in $($CurrentTestData.SetupScript).Split(",")) {
					$null = Run-SetupScript -Script $script -Parameters $TestParameters -VMData $VmData -CurrentTestData $CurrentTestData
				}
			}
		}
	}

	[bool] RestartAllDeployments($AllVMData) {
		foreach ($vm in $AllVMData) {
			$Null = Restart-VMFromShell -VMData $vm
		}
		if ((Is-VmAlive -AllVMDataObject $AllVMData) -eq "True") {
			return $true
		}
		return $false
	}

	[void] RunTestCaseCleanup ($AllVMData, $CurrentTestData, $CurrentTestResult, $CollectVMLogs, $RemoveFiles, $User, $Password, $SetupTypeData, $TestParameters){
		try
		{
			if ($CurrentTestData.CleanupScript) {
				foreach ($VM in $AllVMData) {
					foreach ($script in $($CurrentTestData.CleanupScript).Split(",")) {
						$null = Run-SetupScript -Script $script -Parameters $TestParameters -VMData $VM -CurrentTestData $CurrentTestData
					}				}
			}

			([TestProvider]$this).RunTestCaseCleanup($AllVMData, $CurrentTestData, $CurrentTestResult, $CollectVMLogs, $RemoveFiles, $User, $Password, $SetupTypeData, $TestParameters)
		}
		catch
		{
			$ErrorMessage =  $_.Exception.Message
			Write-Output "EXCEPTION in RunTestCaseCleanup : $ErrorMessage"
		}
	}
}