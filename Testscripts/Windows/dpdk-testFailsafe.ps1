# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

function Set-Test() {
	$vm = "forwarder"
	$nics = Get-NonManagementNic $vm
	$nics[0].EnableIPForwarding = $true
	$nics[0] | Set-AzureRmNetworkInterface

	Write-LogInfo "Enabled ip forwarding on $vm's non management nic"
}

function Set-Runtime() {
	if ($currentPhase -eq "READY_FOR_REVOKE") {
		$nics = Get-NonManagementNic "forwarder"
		$nics[0].EnableAcceleratedNetworking = $false
		$nics[0] | Set-AzureRmNetworkInterface

		Write-LogInfo "VF Revoked"
		Set-Phase "REVOKE_DONE"
	} elseif ($currentPhase -eq "READY_FOR_VF") {
		$nics = Get-NonManagementNic "forwarder"
		$nics[0].EnableAcceleratedNetworking = $true
		$nics[0] | Set-AzureRmNetworkInterface

		Write-LogInfo "VF Re-enabled"
		Set-Phase "VF_RE_ENABLED"
	}
}

function Confirm-Performance() {
	# count is non header lines
	$isEmpty = ($testDataCsv.Count -eq 0)
	if ($isEmpty) {
		throw "No data downloaded from vm"
	}

	foreach($phaseData in $testDataCsv) {
		if ($phaseData.phase -eq "before") {
			$before_rx_pps = [int]$phaseData.fwdrx_pps_avg
			$before_tx_pps = [int]$phaseData.fwdtx_pps_avg

			Write-LogInfo "Before VF revoke performance"
			Write-LogInfo "    TX: $before_tx_pps"
			Write-LogInfo "    RX: $before_rx_pps"
		} elseif ($phaseData.phase -eq "after") {
			$after_rx_pps = [int]$phaseData.fwdrx_pps_avg
			$after_tx_pps = [int]$phaseData.fwdtx_pps_avg

			Write-LogInfo "After VF re-enable performance"
			Write-LogInfo "    TX: $after_tx_pps"
			Write-LogInfo "    RX: $after_rx_pps"
		}
	}

	return (Confirm-WithinPercentage $before_rx_pps $after_rx_pps 10) -and
			(Confirm-WithinPercentage $before_tx_pps $after_tx_pps 10)
}
