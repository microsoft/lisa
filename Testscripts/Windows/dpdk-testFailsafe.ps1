# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

function Configure-Test() {
	$nics = Get-NonManagementNics "forwarder"
	$nics[0].EnableIPForwarding = $true
	$nics[0] | Set-AzureRmNetworkInterface
}

function Alter-Runtime() {
	if ($currentPhase -eq "READY_FOR_REVOKE") {
		$nics = Get-NonManagementNics "forwarder"
		$nics[0].EnableAcceleratedNetworking = $false
		$nics[0] | Set-AzureRmNetworkInterface

		Change-Phase "REVOKE_DONE"
	} elseif ($currentPhase -eq "READY_FOR_VF") {
		$nics = Get-NonManagementNics "forwarder"
		$nics[0].EnableAcceleratedNetworking = $true
		$nics[0] | Set-AzureRmNetworkInterface

		Change-Phase "VF_RE_ENABLED"
	}
}

function Verify-Performance() {
	return
}
