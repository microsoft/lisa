# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

function verifyPerf() {
    $vmSizes = @()
    # error checks made in prepareParameters already
    foreach ($vm in $allVMData) {
        $vmSizes += $vm.InstanceSize
    }
    $vmSize = $vmSizes[0]

    # use temp so when a case fails we still check the rest
    $tempResult = "PASS"
    $testpmdDataCsv = Import-Csv -Path $LogDir\dpdkTestPmd.csv

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

        LogMsg "compare tx pps $($testRun.TxPps) with lowerbound $($coreData.tx)"
        if ([int]$testRun.TxPps -lt [int]$coreData.tx) {
            LogErr "Perf Failure in $($testRun.TestMode) mode; $($testRun.TxPps) must be > $($coreData.tx)"
            $tempResult = "FAIL"
        }

        if ($testRun.TestMode -eq "rxonly") {
            LogMsg "compare rx pps $($testRun.RxPps) with lowerbound $($coreData.rx)"
            if ([int]$testRun.RxPps -lt [int]$coreData.rx) {
                LogErr "Perf Failure in $($testRun.TestMode) mode; $($testRun.RxPps) must be > $($coreData.rx)"
                $tempResult = "FAIL"
            }
        } elseif ($testRun.TestMode -eq "io") {
            LogMsg "compare rx pps $($testRun.RxPps) with lowerbound $($coreData.fwdrx)"
            LogMsg "compare fwdtx pps $($testRun.ReTxPps) with lowerbound $($coreData.fwdtx)"
            if ([int]$testRun.RxPps -lt [int]$coreData.fwdrx) {
                LogErr "Perf Failure in $($testRun.TestMode) mode; $($testRun.RxPps) must be > $($coreData.fwdrx)"
                $tempResult = "FAIL"
            }

            if ([int]$testRun.ReTxPps -lt [int]$coreData.fwdtx) {
                LogErr "Perf Failure in $($testRun.TestMode) mode; $($testRun.ReTxPps) must be > $($coreData.fwdtx)"
                $tempResult = "FAIL"
            }
        } else {
            throw "No pps data for test mode $($testRun.TestMode)"
        }
    }

    return $tempResult
}

function prepareParameters() {
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
        if ($param -imatch "modes") {
            $modes = ($param.Replace("modes=",""))
        } elseif ($param -imatch "cores") {
            $cores = ($param.Replace("cores=",""))
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