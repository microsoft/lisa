# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
<#
.Synopsis
	Check if Network Interfaces are configured correctly in guest VM

.Description
	This is an Azure only test. After the VM is provisioned, additional
	Network Interface(s) will be added. The number of Extra NICs is dynamic
	and is a parameter in the XML test definition. Steps:
	1. Stop VM
	2. Create NIC(s) inside the Resource Groups and attach them to the VM
	3. Start VM
	4. Check if IPs are assigned inside the VM for each new extra NIC
#>

param([object] $AllVmData, [string]$TestParams, [object]$CurrentTestData)

function Main {
	$TestParams = (ConvertFrom-StringData $TestParams.Replace(";","`n"))
	$currentTestResult = Create-TestResultObject
	try {
		$extraNICs = $TestParams.EXTRA_NICS
		$testResult = "FAIL"
		Write-LogDbg "Stopping VM $($AllVMData.RoleName) in RG $($AllVMData.ResourceGroupName)."
		# Stop VM before attaching new NICs
		Stop-AzVM -ResourceGroupName $AllVMData.ResourceGroupName -Name $AllVMData.RoleName `
			-Force | Out-Null
		if (-not $?) {
			Write-LogErr "Failed to stop $($AllVMData.RoleName)"
			return "FAIL"
		}
		Write-LogDbg "Completed VM stopping $($AllVMData.RoleName) in RG $($AllVMData.ResourceGroupName)."
		# Get necessary resources
		$vnet = Get-AzVirtualNetwork -Name "LISAv2-VirtualNetwork" -ResourceGroupName `
			$AllVMData.ResourceGroupName
		$vm = Get-AzVM -ResourceGroupName $AllVMData.ResourceGroupName -Name $AllVMData.RoleName

		# Set the existing NIC as primary
		$vm.NetworkProfile.NetworkInterfaces.Item(0).primary = $true
		Update-AzVM -ResourceGroupName $AllVMData.ResourceGroupName -VM $vm | Out-Null

		for ($nicNr = 1; $nicNr -le $extraNICs; $nicNr++) {
			Write-LogInfo "Setting up NIC #${nicNr}"
			$ipAddr = "10.0.0.${nicNr}0"
			$nicName = "NIC_${nicNr}"
			$ipConfigName = "IPConfig${nicNr}"

			# Add a new network interface
			$ipConfig = New-AzNetworkInterfaceIpConfig -Name $ipConfigName -PrivateIpAddressVersion `
				IPv4 -PrivateIpAddress $ipAddr -SubnetId $vnet.Subnets[0].Id
			if ($CurrentTestData.SetupConfig.Networking -eq 'SRIOV') {
				$nic = New-AzNetworkInterface -Name $nicName -ResourceGroupName $AllVMData.ResourceGroupName `
					-Location $AllVMData.Location -IpConfiguration $ipConfig -Force -EnableAcceleratedNetworking
			}
			else {
				$nic = New-AzNetworkInterface -Name $nicName -ResourceGroupName $AllVMData.ResourceGroupName `
					-Location $AllVMData.Location -IpConfiguration $ipConfig -Force
			}
			Add-AzVMNetworkInterface -VM $vm -Id $nic.Id | Out-Null
			if (-not $?) {
				Write-LogErr "Failed to create extra NIC #${nicNr} in $($AllVMData.ResourceGroupName)"
				return "FAIL"
			}
			Start-Sleep -Seconds 5
			Write-LogInfo "Successfully added extra NIC #${nicNr}!"
		}
		Write-LogDbg "Updating VM $($AllVMData.RoleName) in RG $($AllVMData.ResourceGroupName)."
		Update-AzVM -ResourceGroupName $AllVMData.ResourceGroupName -VM $vm | Out-Null
		if (-not $?) {
			Write-LogErr "Failed to update the VM $($AllVMData.RoleName) with new NIC(s)"
			return "FAIL"
		}
		Write-LogDbg "Completed VM updating $($AllVMData.RoleName) in RG $($AllVMData.ResourceGroupName)."
		# Start VM
		$startVMScriptBlock = {
			param($VMData)
			Start-AzVM -ResourceGroupName $VMData.ResourceGroupName -Name $VMData.RoleName -NoWait | Out-Null
		}
		Write-LogDbg "Starting VM $($AllVMData.RoleName) in RG $($AllVMData.ResourceGroupName)."
		$startVMResult = Wait-AzVMBackRunningWithTimeOut -AllVMData $AllVMData -AzVMScript $startVMScriptBlock -MaxRetryCount 30
		if (!$startVMResult) {
			Write-LogErr "Starting VM $($AllVMData.RoleName) failed in RG $($AllVMData.ResourceGroupName)."
			return "FAIL"
		}

		# Verify if each extra NIC gets IP
		for ($nicNr = 1; $nicNr -le $extraNICs; $nicNr++) {
			Write-LogInfo "Checking IP for Extra NIC #${nicNr}"
			$ipAddr = "10.0.0.${nicNr}0"
			$ipCount = Run-LinuxCmd -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password `
				$password -command "export PATH=`$PATH:/usr/sbin ; ip a | grep -c $ipAddr" -ignoreLinuxExitCode:$true
			if ($ipCount -eq 1) {
				Write-LogInfo "Extra NIC #${nicNr} is correctly configured!"
			} else {
				Write-LogErr "Extra NIC #${nicNr} didn't get the expected IP ${ipAddr}"
				return "FAIL"
			}
		}
		$testResult = "PASS"
	} catch {
		$ErrorMessage =  $_.Exception.Message
		Write-LogErr "EXCEPTION : $ErrorMessage"
	} finally {
		if (!$testResult) {
			$testResult = "Aborted"
		}
		$resultArr += $testResult
	}

	$currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
	return $currentTestResult
}

Main