# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

function Confirm-Performance() {
	$vmSizes = @()

	foreach ($vm in $allVMData) {
		$vmSizes += $vm.InstanceSize
	}
	$vmSize = $vmSizes[0]

	# use temp so when a case fails we still check the rest
	$tempResult = "PASS"

	$allPpsData = [Xml](Get-Content .\XML\Other\testpmd_pps_lowerbound.xml)
	$sizeData = Select-Xml -Xml $allPpsData -XPath "testpmdpps/$vmSize" | Select-Object -ExpandProperty Node

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
		if ([int]$testRun.tx_pps_avg -lt [int]$coreData.tx) {
			Write-LogErr "  Perf Failure in $($testRun.test_mode) mode; $($testRun.tx_pps_avg) must be > $($coreData.tx)"
			$tempResult = "FAIL"
		}

		if ($testRun.test_mode -eq "rxonly") {
			Write-LogInfo "  compare rx pps $($testRun.rx_pps_avg) with lowerbound $($coreData.rx)"
			if ([int]$testRun.rx_pps_avg -lt [int]$coreData.rx) {
				Write-LogErr "  Perf Failure in $($testRun.test_mode) mode; $($testRun.rx_pps_avg) must be > $($coreData.rx)"
				$tempResult = "FAIL"
			}
		} elseif ($testRun.test_mode -eq "io") {
			Write-LogInfo "  compare rx pps $($testRun.rx_pps_avg) with lowerbound $($coreData.fwdrx)"
			Write-LogInfo "  compare fwdtx pps $($testRun.fwdtx_pps_avg) with lowerbound $($coreData.fwdtx)"
			if ([int]$testRun.rx_pps_avg -lt [int]$coreData.fwdrx) {
				Write-LogErr "  Perf Failure in $($testRun.test_mode) mode; $($testRun.rx_pps_avg) must be > $($coreData.fwdrx)"
				$tempResult = "FAIL"
			}

			if ([int]$testRun.fwdtx_pps_avg -lt [int]$coreData.fwdtx) {
				Write-LogErr "  Perf Failure in $($testRun.test_mode) mode; $($testRun.fwdtx_pps_avg) must be > $($coreData.fwdtx)"
				$tempResult = "FAIL"
			}
		} else {
			throw "No pps data for test mode $($testRun.test_mode)"
		}
	}

	return $tempResult
}
