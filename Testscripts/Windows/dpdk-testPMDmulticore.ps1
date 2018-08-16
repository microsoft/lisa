# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

function castStrToInt([string]$candidate) {
    [int]$number = $null

    if ([int32]::TryParse($candidate, [ref]$number)) {
        return $number
    } else {
        throw "Failed to cast str to int"
    }
}

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
        $msg = "No pps data for VM size $vmSize"
        LogMsg $msg
        throw $msg
    }

    # count is non header lines
    $isEmpty = ($testpmdDataCsv.Count -eq 0)
    if ($isEmpty) {
        $msg = "No data downloaded from vm"
        LogMsg $msg
        throw $msg
    }

    foreach($testRun in $testpmdDataCsv) {
        $coreData = Select-Xml -Xml $sizeData -XPath "core$($testRun.core)" | Select-Object -ExpandProperty Node

        LogMsg "comparing tx pps $($testRun.TxPps) with lowerbound $($coreData.tx)"
        if ((castStrToInt($testRun.TxPps)) -lt (castStrToInt($coreData.tx))) {
            LogMsg "Perf Failure in $($testRun.TestMode) mode; $($testRun.TxPps) must be > $($coreData.tx)"
            $tempResult = "FAIL"
        }

        if ($testRun.TestMode -eq "rxonly") {
            LogMsg "compare rx pps $($testRun.RxPps) with lowerbound $($coreData.rx)"
            if ((castStrToInt($testRun.RxPps)) -lt (castStrToInt($coreData.rx))) {
                LogMsg "Perf Failure in $($testRun.TestMode) mode; $($testRun.RxPps) must be > $($coreData.rx)"
                $tempResult = "FAIL"
            }
        } elseif ($testRun.TestMode -eq "io") {
            LogMsg "compare rx pps $($testRun.RxPps) with lowerbound $($coreData.fwdrx)"
            LogMsg "compare fwdtx pps $($testRun.ReTxPps) with lowerbound $($coreData.fwdtx)"
            if ((castStrToInt($testRun.RxPps)) -lt (castStrToInt($coreData.fwdrx))) {
                LogMsg "Perf Failure in $($testRun.TestMode) mode; $($testRun.RxPps) must be > $($coreData.fwdrx)"
                $tempResult = "FAIL"
            }

            if ((castStrToInt($testRun.ReTxPps)) -lt (castStrToInt($coreData.fwdtx))) {
                LogMsg "Perf Failure in $($testRun.TestMode) mode; $($testRun.ReTxPps) must be > $($coreData.fwdtx)"
                $tempResult = "FAIL"
            }
        } else {
            # should add other modes then rely on cast failing, but error is more unclear
            # could try catch and rethrow
            $msg = "No pps data for test mode $($testRun.TestMode)"
            LogMsg $msg
            throw $msg
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
        $msg = "Test only supports two VMs"
        LogMsg $msg
        throw $msg
    }

    if ($vmSizes[0] -ne $vmSizes[1]) {
        $msg = "Test only supports VMs of same size"
        LogMsg $msg
        throw $msg
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
            $coreNum = castStrToInt($coreStr)
            if ($coreNum -gt $maxCore) {
                $maxCore = $coreNum
            }
        }

        switch ($vmSize) {
            "Standard_DS4_v2" {
                if ($maxCore -gt 7) {
                    $errorMsg = "Too many cores, cannot be > 7"
                    LogMsg $errorMsg
                    throw $errorMsg
                }
            }

            "Standard_DS15_v2" {
                if ($maxCore -gt 19) {
                    $errorMsg = "Too many cores, cannot be > 19"
                    LogMsg $errorMsg
                    throw $errorMsg
                }
            }
        }

        LogMsg "Cores $cores test on $vmSize"
    }
}