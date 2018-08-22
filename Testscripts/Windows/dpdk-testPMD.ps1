# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

function Verify-Performance() {
	$vmSizes = @()
	# error checks made in prepareParameters already
	foreach ($vm in $allVMData) {
		$vmSizes += $vm.InstanceSize
	}
	$vmSize = $vmSizes[0]

	# use temp so when a case fails we still check the rest
	$tempResult = "PASS"
	$testpmdDataCsv = Import-Csv -Path $LogDir\dpdk_testpmd.csv

	$allPpsData = [Xml](Get-Content .\XML\Other\pps_lowerbound.xml)
	$sizeData = Select-Xml -Xml $allPpsData -XPath "testpmdpps/$vmSize" | Select-Object -ExpandProperty Node

	if ($null -eq $sizeData) {
		throw "No pps data for VM size $vmSize"
	}

	# count is non header lines
	$isEmpty = ($testpmdDataCsv.Count -eq 0)
	if ($isEmpty) {
		throw "No data downloaded from vm"
	}

	foreach($testRun in $testpmdDataCsv) {
		$coreData = Select-Xml -Xml $sizeData -XPath "core$($testRun.core)" | Select-Object -ExpandProperty Node
		LogMsg "Comparing $($testRun.core) core(s) data"
		LogMsg "  compare tx pps $($testRun.tx_pps_avg) with lowerbound $($coreData.tx)"
		if ([int]$testRun.tx_pps_avg -lt [int]$coreData.tx) {
			LogErr "  Perf Failure in $($testRun.test_mode) mode; $($testRun.tx_pps_avg) must be > $($coreData.tx)"
			$tempResult = "FAIL"
		}

		if ($testRun.test_mode -eq "rxonly") {
			LogMsg "  compare rx pps $($testRun.rx_pps_avg) with lowerbound $($coreData.rx)"
			if ([int]$testRun.rx_pps_avg -lt [int]$coreData.rx) {
				LogErr "  Perf Failure in $($testRun.test_mode) mode; $($testRun.rx_pps_avg) must be > $($coreData.rx)"
				$tempResult = "FAIL"
			}
		# fwd corresponds to testpmd's io mode
		} elseif ($testRun.test_mode -eq "fwd") {
			LogMsg "  compare rx pps $($testRun.rx_pps_avg) with lowerbound $($coreData.fwdrx)"
			LogMsg "  compare fwdtx pps $($testRun.fwdtx_pps_avg) with lowerbound $($coreData.fwdtx)"
			if ([int]$testRun.rx_pps_avg -lt [int]$coreData.fwdrx) {
				LogErr "  Perf Failure in $($testRun.test_mode) mode; $($testRun.rx_pps_avg) must be > $($coreData.fwdrx)"
				$tempResult = "FAIL"
			}

			if ([int]$testRun.fwdtx_pps_avg -lt [int]$coreData.fwdtx) {
				LogErr "  Perf Failure in $($testRun.test_mode) mode; $($testRun.fwdtx_pps_avg) must be > $($coreData.fwdtx)"
				$tempResult = "FAIL"
			}
		} else {
			throw "No pps data for test mode $($testRun.test_mode)"
		}
	}

	return $tempResult
}

function Prepare-Parameters() {
	$vmSizes = @()
	foreach ($vm in $allVMData) {
		$vmSizes += $vm.InstanceSize
	}

	if ($vmSizes.count -ne 2) {
		throw "Test only supports two VMs"
	}

	if ($vmSizes[0] -ne $vmSizes[1]) {
		throw "Test only supports VMs of same size"
	}
	$vmSize = $vmSizes[0]

	foreach ($param in $currentTestData.TestParameters.param) {
		Add-Content -Value "$param" -Path $constantsFile
		if ($param -imatch "MODES") {
			$modes = ($param.Replace("MODES=",""))
		} elseif ($param -imatch "CORES") {
			$cores = ($param.Replace("CORES=",""))
		}
	}

	LogMsg "test modes: $modes"
	if ($null -eq $cores) {
		LogMsg "Single core test on $vmSize"
	} else {
		$cores = $cores -replace '"',''
		$coresArray = $cores.split(' ')
		$maxCore = 0
		foreach ($coreStr in $coresArray) {
			$coreNum = [int]$coreStr
			if ($coreNum -gt $maxCore) {
				$maxCore = $coreNum
			}
		}

		switch ($vmSize) {
			"Standard_DS4_v2" {
				if ($maxCore -gt 7) {
					throw "Too many cores, cannot be > 7"
				}
			}

			"Standard_DS15_v2" {
				if ($maxCore -gt 19) {
					throw "Too many cores, cannot be > 19"
				}
			}
		}

		LogMsg "Cores $cores test on $vmSize"
	}
}