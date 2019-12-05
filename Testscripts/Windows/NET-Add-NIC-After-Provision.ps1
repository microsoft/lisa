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

param([object] $AllVmData, [string]$TestParams)

function Main {
	param($AllVMData, $TestParams)
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
		$vnet = Get-AzVirtualNetwork -Name "VirtualNetwork" -ResourceGroupName `
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
			$nic = New-AzNetworkInterface -Name $nicName -ResourceGroupName $AllVMData.ResourceGroupName `
				-Location $AllVMData.Location -IpConfiguration $ipConfig -Force
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
		Write-LogDbg "Starting VM $($AllVMData.RoleName) in RG $($AllVMData.ResourceGroupName)."
		Start-AzVM -ResourceGroupName $AllVMData.ResourceGroupName -Name $AllVMData.RoleName -NoWait | Out-Null
		if (-not $?) {
			Write-LogErr "Failed to start $($AllVMData.RoleName)"
			return "FAIL"
		}
		$vm = Get-AzVM -ResourceGroupName $AllVMData.ResourceGroupName -Name $AllVMData.RoleName -Status
		$MaxAttempts = 30
		while (($vm.Statuses[-1].Code -ne "PowerState/running") -and ($MaxAttempts -gt 0)) {
			Write-LogDbg "Attempt $(31 - $MaxAttempts) - VM $($AllVMData.RoleName) is in $($vm.Statuses[-1].Code) state, still not in running state, wait for 20 seconds..."
			Start-Sleep -Seconds 20
			$MaxAttempts -= 1
			$vm = Get-AzVM -ResourceGroupName $AllVMData.ResourceGroupName -Name $AllVMData.RoleName -Status
		}
		if ($vm.Statuses[-1].Code -ne "PowerState/running") {
			Write-LogErr "Test case timed out waiting for VM to boot"
			return "FAIL"
		}
		$vmData = Get-AllDeploymentData -ResourceGroups $AllVMData.ResourceGroupName
		$AllVMData.PublicIP = $vmData.PublicIP

		# Waiting for the VM to run again and respond to SSH - port 22
		$retval = Wait-ForVMToStartSSH -Ipv4addr $AllVMData.PublicIP -StepTimeout 600
		if ($retval -eq $False) {
			Write-LogErr "Test case timed out waiting for VM to boot"
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

Main -allVMData $AllVmData -TestParams (ConvertFrom-StringData $TestParams.Replace(";","`n"))