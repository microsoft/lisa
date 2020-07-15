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
			Add-Member -InputObject $objNode -MemberType NoteProperty -Name InternalIP -Value $null -Force
			Add-Member -InputObject $objNode -MemberType NoteProperty -Name InstanceSize -Value $null -Force
			return $objNode
		}

		function GetIPv4AddressFromIpAddrInfo([string] $ipAddrInfo) {
			Write-LogDbg "Get IPv4 address from command output of 'ip address show': $ipAddrInfo"
			[regex] $re = "(?:[0-9]{1,3}\.){3}[0-9]{1,3}"
			[string] $matchedIp = $re.Match($ipAddrInfo)
			return $matchedIp
		}

		function SetInternalIPv4Address([object] $AllVMData) {
			$count = 0
			foreach ($vmData in $AllVMData) {
				# get the first active nic device's IPv4 address. This is the temporary approach, as it may not be right for VMs that have multi nic devices.
				$ipAddrInfo = Run-LinuxCmd -username $global:user -password $global:password -ip $($vmData.PublicIp) -port $($vmData.SSHPort) `
					-command "ip -4 address | awk -F': ' '!/lo/ {print `$2}' | xargs ip address show" -RunAsSudo
				$ipAddress = GetIPv4AddressFromIpAddrInfo -ipAddrInfo $ipAddrInfo
				if ($ipAddress) {
					$AllVmData[$count].InternalIP = $ipAddress
				} else {
					Write-LogErr "Cannot get the internal IP address for $($vmData.PublicIp):$($vmData.SSHPort)"
				}
				$count++
			}
		}

		function SetInstanceSize([object] $AllVmData) {
			$count = 0
			foreach ($vmData in $AllVMData) {
				if ($global:OverrideVMSize) {
					$AllVmData[$count].InstanceSize = $global:OverrideVMSize
				} else {
					$coreCount = Run-LinuxCmd -username $global:user -password $global:password -ip $($vmData.PublicIp) -port $($vmData.SSHPort) `
						-command "cat /proc/cpuinfo | grep -c ^processor"
					$memGB = Run-LinuxCmd -username $global:user -password $global:password -ip $($vmData.PublicIp) -port $($vmData.SSHPort) `
						-command "free -g | grep Mem | awk {'print `$2'}"
					$AllVmData[$count].InstanceSize = "${coreCount}_CPU_${memGB}_GB_Mem"
				}
				$count++
			}
		}

		$allVMData = @()
		$ErrorMessage = ""
		try {
			$allVmList = $TestLocation.Split(",");
			$machines = @()
			$machines += $SetupTypeData.ResourceGroup.VirtualMachine

			if ($allVmList.Count -lt $machines.Count) {
				Write-LogErr "Not enough test targets provided for case $($TestCaseData.TestName)"
				return $null
			}

			$vmIndex = 0
			while ($vmIndex -lt $machines.Count) {
				$vmNode = Create-QuickVMNode

				$vmInfo = $allVmList[$vmIndex]
				$vmNode.PublicIP = $vmInfo.Split(":")[0]
				$vmNode.SSHPort = $vmInfo.Split(":")[1]
				$vmNode.UserName = $Global:user
				$vmNode.Password = $Global:password
				$vmNode.RoleName = "Role-$vmIndex"
				$allVMData += $vmNode;
				$vmIndex++
			}

			$isVmAlive = Is-VmAlive -AllVMDataObject $allVMData
			if ($isVmAlive -ne "True") {
				Write-LogErr "Unable to connect SSH ports.."
				return $null
			}
			SetInternalIPv4Address -AllVMData $allVMData
			SetInstanceSize -AllVmData $allVMData
			Write-LogInfo("No need to deploy new VM as this test case is running against a prepared environment.")
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
		# Do nothing
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
					}
				}
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