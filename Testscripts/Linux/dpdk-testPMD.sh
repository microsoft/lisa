#!/bin/bash
#
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

#############################################################################
#
# dpdk-testPMDmulticore.sh
# Description:
#	This script runs testpmd in various modes scaling across various cores.
# 	It places testpmd output in $LOGDIR, and the parses output to get avg pps
# 	numbers. The accompanying ps1 script makes sure testpmd performs above the
#	required threshold.
#
#############################################################################

# call with cores
runTestPmd() {	
    if [ -z "${1}" ]; then
        LogErr "ERROR: Must provide core list as argument 1 to runTestPmd()"
        SetTestStateAborted
        exit 1
    fi

    if [ -z "${testDuration}" ]; then
        testDuration=120
        LogMsg "testDuration not provided to runTestPmd(); using default $testDuration"
    fi

    if [ -z "${modes}" ]; then
        modes="rxonly io"
        LogMsg "modes parameter not provided to runTestPmd(); using default $modes"
    fi

    if [ -z "${LIS_HOME}" -o -z "${LOGDIR}" ]; then
        LogErr "ERROR: LIS_HOME and LOGDIR must be defined"
        SetTestStateAborted
        exit 1
    fi

    core=${1}
    dpdkSrcDir=$(ls | grep dpdk- | grep -v \.sh)

    pairs=($(getSyntheticVfPairs))
    if [ -z "${pairs[@]}" ]; then
        LogErr "ERROR: No VFs present"
        SetTestStateFailed
        exit 1
    fi

    iface="${pairs[0]}"
    busaddr="${pairs[1]}"

    for testmode in $modes; do
        LogMsg "Ensuring free hugepages"
        freeHugeCMD="rm -rf /dev/hugepages/*"
        ssh ${server} $freeHugeCMD
        eval $freeHugeCMD

        serverDuration=$(expr $testDuration + 5)

        # update to use 2nd NIC
        serverTestPmdCmd="timeout ${serverDuration} $LIS_HOME/$dpdkSrcDir/build/app/testpmd -l 0-${core} -w ${busaddr} --vdev='net_vdev_netvsc0,iface=${iface}' -- --port-topology=chained --nb-cores ${core} --txq ${core} --rxq ${core} --mbcache=512 --txd=4096 --rxd=4096 --forward-mode=${testmode} --stats-period 1"
        LogMsg "${serverTestPmdCmd}"
        ssh ${server} $serverTestPmdCmd 2>&1 > $LOGDIR/dpdk-testpmd-${testmode}-receiver-${core}-core-$(date +"%m%d%Y-%H%M%S").log &

        sleep 5
        
        # should scale memory channels 2 * NUM_NUMA_NODES
        clientTestPmdCmd="timeout ${testDuration} $LIS_HOME/$dpdkSrcDir/build/app/testpmd -l 0-${core} -w ${busaddr} --vdev='net_vdev_netvsc0,iface=${iface}' -- --port-topology=chained --nb-cores ${core} --txq ${core} --rxq ${core} --mbcache=512 --txd=4096 --forward-mode=txonly --stats-period 1 2>&1 > $LOGDIR/dpdk-testpmd-${testmode}-sender-${core}-core-$(date +"%m%d%Y-%H%M%S").log &"
        LogMsg "${clientTestPmdCmd}"
        eval $clientTestPmdCmd

        sleep ${testDuration}

        LogMsg "killing testpmd"
        killCMD="pkill testpmd"
        ssh ${server} $killCMD
        eval $killCMD

        LogMsg "TestPmd execution for ${testmode} mode on ${core} core(s) is COMPLETED"
        sleep 10
    done	
}

# call with cores
testPmdParser() {
    if [ -z "${1}" ]; then
        LogErr "ERROR: Must provide core list as argument 1 to testPmdParser()"
        SetTestStateAborted
        exit 1
    fi

    if [ -z "${dpdkSrcLink}" ]; then
        LogErr "ERROR: dpdkSrcLink missing from constants file"
        SetTestStateAborted
        exit 1
    fi

    if [ -z "${LIS_HOME}" -o -z "${LOGDIR}" ]; then
        LogErr "ERROR: LIS_HOME and LOGDIR must be global"
        SetTestStateAborted
        exit 1
    fi

    core=${1}
    dpdkSrcDir=$(ls | grep dpdk- | grep -v \.sh)
    dpdkVersion=$(echo $dpdkSrcLink | grep -Po "(\d+\.)+\d+")
    testpmdCsvFile=$LIS_HOME/dpdkTestPmd.csv
    logFiles=($(ls $LOGDIR/*.log))
    fileCount=0

    while [ "x${logFiles[$fileCount]}" != "x" ]
    do
        LogMsg "collecting results from ${logFiles[$fileCount]}"
        if [[ ${logFiles[$fileCount]} =~ "rxonly-receiver-${core}-core" ]];	then
            rxonly_mode="rxonly"
            rxonly_Rxpps_Max=$(cat ${logFiles[$fileCount]} | grep Rx-pps: | awk '{print $2}' | sort -n | tail -1)
            rxonly_Rxpps=($(cat ${logFiles[$fileCount]} | grep Rx-pps: | awk '{print $2}'))
            rxonly_Rxpps_Avg=$(($(expr $(printf '%b + ' "${rxonly_Rxpps[@]::${#rxonly_Rxpps[@]}}"\\c))/${#rxonly_Rxpps[@]}))

            rxonly_ReTxpps_Max=$(cat ${logFiles[$fileCount]} | grep Tx-pps: | awk '{print $2}' | sort -n | tail -1)
            rxonly_ReTxpps=($(cat ${logFiles[$fileCount]} | grep Tx-pps: | awk '{print $2}'))
            rxonly_ReTxpps_Avg=$(($(expr $(printf '%b + ' "${rxonly_ReTxpps[@]::${#rxonly_ReTxpps[@]}}"\\c))/${#rxonly_ReTxpps[@]}))
        elif [[ ${logFiles[$fileCount]} =~ "rxonly-sender-${core}-core" ]]; then
            rxonly_mode="rxonly"
            rxonly_Txpps_Max=($(cat ${logFiles[$fileCount]} | grep Tx-pps: | awk '{print $2}' | sort -n | tail -1))
            rxonly_Txpps=($(cat ${logFiles[$fileCount]} | grep Tx-pps: | awk '{print $2}'))
            rxonly_Txpps_Avg=$(($(expr $(printf '%b + ' "${rxonly_Txpps[@]::${#rxonly_Txpps[@]}}"\\c))/${#rxonly_Txpps[@]}))
        elif [[ ${logFiles[$fileCount]} =~ "io-receiver-${core}-core" ]]; then
            io_mode="io"
            io_Rxpps_Max=$(cat ${logFiles[$fileCount]} | grep Rx-pps: | awk '{print $2}' | sort -n | tail -1)
            io_Rxpps=($(cat ${logFiles[$fileCount]} | grep Rx-pps: | awk '{print $2}'))
            io_Rxpps_Avg=$(($(expr $(printf '%b + ' "${io_Rxpps[@]::${#io_Rxpps[@]}}"\\c))/${#io_Rxpps[@]}))

            io_ReTxpps_Max=$(cat ${logFiles[$fileCount]} | grep Tx-pps: | awk '{print $2}' | sort -n | tail -1)
            io_ReTxpps=($(cat ${logFiles[$fileCount]} | grep Tx-pps: | awk '{print $2}'))
            io_ReTxpps_Avg=$(($(expr $(printf '%b + ' "${io_ReTxpps[@]::${#io_ReTxpps[@]}}"\\c))/${#io_ReTxpps[@]}))
        elif [[ ${logFiles[$fileCount]} =~ "io-sender-${core}-core" ]]; then
            io_mode="io"
            io_Txpps_Max=($(cat ${logFiles[$fileCount]} | grep Tx-pps: | awk '{print $2}' | sort -n | tail -1))
            io_Txpps=($(cat ${logFiles[$fileCount]} | grep Tx-pps: | awk '{print $2}'))
            io_Txpps_Avg=$(($(expr $(printf '%b + ' "${io_Txpps[@]::${#io_Txpps[@]}}"\\c))/${#io_Txpps[@]}))
        fi
        ((fileCount++))
    done
    if [[ $rxonly_mode == "rxonly" ]];then
        LogMsg "$rxonly_mode pushing to csv file"
        echo "$dpdkVersion,$rxonly_mode,${core},$rxonly_Rxpps_Max,$rxonly_Txpps_Avg,$rxonly_Rxpps_Avg,$rxonly_ReTxpps_Avg" >> $testpmdCsvFile
    fi
    if [[ $io_mode == "io" ]];then
        LogMsg "$io_mode pushing to csv file"	
        echo "$dpdkVersion,$io_mode,${core},$io_Rxpps_Max,$io_Txpps_Avg,$io_Rxpps_Avg,$io_ReTxpps_Avg" >> $testpmdCsvFile
    fi
}

runTestcase() {
    if [ -z "${cores}" ]; then
        LogMsg "cores parameter not provided; doing default single core test"
        cores="1"
    fi

    LogMsg "Starting TestPmd test execution with DPDK"
    for core in $cores; do
        runTestPmd $core
    done

    LogMsg "Starting TestPmd results parser execution"
    echo "DpdkVersion,TestMode,Core,MaxRxPps,TxPps,RxPps,ReTxPps" > $LIS_HOME/dpdkTestPmd.csv
    for core in $cores; do
        testPmdParser $core
    done

    LogMsg "TestPmd RESULTS"
    column -s, -t $LIS_HOME/dpdkTestPmd.csv
}