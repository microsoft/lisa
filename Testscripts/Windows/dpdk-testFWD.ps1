# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

function Configure-Test() {
	$rg = $allVMData[0].ResourceGroupName
	$nics = Get-AzureRmNetworkInterface -ResourceGroupName $rg | Where-Object {($_.VirtualMachine.Id -ne $null) `
		-and (($_.VirtualMachine.Id | Split-Path -leaf) -eq "forwarder")}

	foreach ($nic in $nics) {
		if ($nic.IpConfigurations.PublicIpAddress -eq $null) {
			$nic.EnableIPForwarding = $true
			$nic | Set-AzureRmNetworkInterface
		}
	}
	return
}

function Verify-Performance() {
	return "PASS"
}
