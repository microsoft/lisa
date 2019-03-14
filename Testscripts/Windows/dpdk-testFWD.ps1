# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

function Set-Test() {
	$vm = "forwarder"
	$nics = Get-NonManagementNic $vm
	$nics[0].EnableIPForwarding = $true
	$nics[0] | Set-AzureRmNetworkInterface

	Write-LogInfo "Enabled ip forwarding on $vm's non management nic"
}

function Confirm-Performance() {
	$vmSizes = @()

	foreach ($vm in $allVMData) {
		$vmSizes += $vm.InstanceSize
	}
	$vmSize = $vmSizes[0]

	# use temp so when a case fails we still check the rest
	$tempResult = "PASS"

	$allPpsData = [Xml](Get-Content .\XML\Other\testfwd_pps_lowerbound.xml)
	$sizeData = Select-Xml -Xml $allPpsData -XPath "testfwdpps/$vmSize" | Select-Object -ExpandProperty Node

	if ($null -eq $sizeData) {
		throw "No pps data for VM size $vmSize"
	}

	# count is non header lines
	$isEmpty = ($testDataCsv.Count -eq 0)
	if ($isEmpty) {
		throw "No data downloaded from vm"
	}

	foreach($testRun in $testDataCsv) {
		$coreData = Select-Xml -Xml $sizeData -XPath "core$($testRun.core)" | Select-Object -ExpandProperty Node
		Write-LogInfo "Comparing $($testRun.core) core(s) data"
		Write-LogInfo "  compare tx pps $($testRun.tx_pps_avg) with lowerbound $($coreData.tx)"
		if (!(Confirm-WithinPercentage $testRun.tx_pps_avg $coreData.tx)) {
			Write-LogErr "  Perf Failure; $($testRun.tx_pps_avg) must be > $($coreData.tx)"
			$tempResult = "FAIL"
		}

		Write-LogInfo "  compare fwdrx pps $($testRun.fwdrx_pps_avg) with lowerbound $($coreData.fwdrx)"
		if (!(Confirm-WithinPercentage $testRun.fwdrx_pps_avg $coreData.fwdrx)) {
			Write-LogErr "  Perf Failure; $($testRun.fwdrx_pps_avg) must be > $($coreData.fwdrx)"
			$tempResult = "FAIL"
		}

		Write-LogInfo "  compare fwdtx pps $($testRun.fwdtx_pps_avg) with lowerbound $($coreData.fwdtx)"
		if (!(Confirm-WithinPercentage $testRun.fwdtx_pps_avg $coreData.fwdtx)) {
			Write-LogErr "  Perf Failure; $($testRun.fwdtx_pps_avg) must be > $($coreData.fwdtx)"
			$tempResult = "FAIL"
		}

		Write-LogInfo "  compare rx pps $($testRun.rx_pps_avg) with lowerbound $($coreData.rx)"
		if (!(Confirm-WithinPercentage $testRun.rx_pps_avg $coreData.rx)) {
			Write-LogErr "  Perf Failure; $($testRun.rx_pps_avg) must be > $($coreData.rx)"
			$tempResult = "FAIL"
		}
	}

	return $tempResult
}

