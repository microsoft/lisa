#!/bin/bash
#
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

#############################################################################
#
# dpdk-testPMD.sh
# Description:
#	This script runs testpmd in various modes scaling across various cores.
# 	It places testpmd output in $LOG_DIR, and then parses output to get avg pps
# 	numbers. The accompanying ps1 script makes sure testpmd performs above the
#	required threshold.
#
#############################################################################

# Requires
#   - UtilsInit
#   - core, modes, and test_duration as arguments in that order
#   - LOG_DIR and SERVER to be defined
function run_testpmd() {
    if [ -z "${1}" -o -z "${2}" -o -z "${3}" ]; then
        LogErr "ERROR: Must provide core, modes, test_duration as arguments in that order to run_testpmd()"
        SetTestStateAborted
        exit 1
    fi

    if [ -z "${LIS_HOME}" -o -z "${LOG_DIR}" -o -z "${SERVER}" ]; then
        LogErr "ERROR: LIS_HOME, LOG_DIR, and SERVER must be defined in environment"
        SetTestStateAborted
        exit 1
    fi

    local core=${1}
    local modes=${2}
    local test_duration=${3}
    local dpdk_dir=$(ls ${LIS_HOME} | grep dpdk- | grep -v \.sh)

    local pairs=($(get_synthetic_vf_pairs))
    if [ "${#pairs[@]}" -eq 0 ]; then
        LogErr "ERROR: No VFs present"
        SetTestStateFailed
        exit 1
    fi

    local iface="${pairs[0]}"
    local bus_addr="${pairs[1]}"

    for test_mode in ${modes}; do
        LogMsg "Ensuring free hugepages"
        local free_huge_cmd="rm -rf /dev/hugepages/*"
        ssh ${SERVER} ${free_huge_cmd}
        eval ${free_huge_cmd}

        # start server in advance so traffic spike doesn't cause output freeze
        local server_duration=$(expr ${test_duration} + 5)

        local pmd_mode=${test_mode}
        if [ "${test_mode}" = "fwd" ]; then
            pmd_mode="io"
        fi
        local server_testpmd_cmd="timeout ${server_duration} ${LIS_HOME}/${dpdk_dir}/build/app/testpmd -l 0-${core} -w ${bus_addr} --vdev='net_vdev_netvsc0,iface=${iface}' -- --port-topology=chained --nb-cores ${core} --txq ${core} --rxq ${core} --mbcache=512 --txd=4096 --rxd=4096 --forward-mode=${pmd_mode} --stats-period 1"
        LogMsg "${server_testpmd_cmd}"
        ssh ${SERVER} ${server_testpmd_cmd} 2>&1 > ${LOG_DIR}/dpdk-testpmd-${test_mode}-receiver-${core}-core-$(date +"%m%d%Y-%H%M%S").log &

        sleep 5
        
        # should scale memory channels 2 * NUM_NUMA_NODES
        local client_testpmd_cmd="timeout ${test_duration} ${LIS_HOME}/${dpdk_dir}/build/app/testpmd -l 0-${core} -w ${bus_addr} --vdev='net_vdev_netvsc0,iface=${iface}' -- --port-topology=chained --nb-cores ${core} --txq ${core} --rxq ${core} --mbcache=512 --txd=4096 --forward-mode=txonly --stats-period 1 2>&1 > ${LOG_DIR}/dpdk-testpmd-${test_mode}-sender-${core}-core-$(date +"%m%d%Y-%H%M%S").log &"
        LogMsg "${client_testpmd_cmd}"
        eval ${client_testpmd_cmd}

        sleep ${test_duration}

        LogMsg "killing testpmd"
        local kill_cmd="pkill testpmd"
        eval ${kill_cmd}
        ssh ${SERVER} ${kill_cmd}

        LogMsg "TestPmd execution for ${test_mode} mode on ${core} core(s) is COMPLETED"
        sleep 10
    done	
}

# Requires
#   - UtilsInit
#   - arguments in order: core, test_mode, csv file
#   - LOG_DIR to be defined
function testpmd_parser() {
    if [ -z "${1}" -o -z "${2}" -o -z "${3}" ]; then
        LogErr "ERROR: Must provide core, test_mode, and csv file in that order to test_pmd_parser()"
        SetTestStateAborted
        exit 1
    fi

    if [ -z "${LOG_DIR}" ]; then
        LogErr "ERROR: LOG_DIR must be defined"
        SetTestStateAborted
        exit 1
    fi

    local core=${1}
    local test_mode=${2}
    local testpmd_csv_file=${3}
    local dpdk_dir=$(ls ${LIS_HOME} | grep dpdk- | grep -v \.sh)
    local dpdk_version=$(grep "Version:" ${LIS_HOME}/${dpdk_dir}/pkg/dpdk.spec | awk '{print $2}')

    local log_files=$(ls ${LOG_DIR}/*.log | grep "dpdk-testpmd-${test_mode}-.*-${core}-core")
    LogMsg "Parsing test run ${test_mode} mode ${core} core(s)"
    for file in ${log_files}; do
        LogMsg "  Reading ${file}"
        if [[ "${file}" =~ "receiver" ]]; then
            rx_pps_arr=($(grep Rx-pps: ${file} | awk '{print $2}' | sort -n))
            rx_pps_avg=$(( ($(printf '%b + ' "${rx_pps_arr[@]}"\\c)) / ${#rx_pps_arr[@]} ))

            fwdtx_pps_arr=($(grep Tx-pps: ${file} | awk '{print $2}' | sort -n))
            fwdtx_pps_avg=$(( ($(printf '%b + ' "${fwdtx_pps_arr[@]}"\\c)) / ${#fwdtx_pps_arr[@]} ))
        elif [[ "${file}" =~ "sender" ]]; then
            tx_pps_arr=($(grep Tx-pps: ${file} | awk '{print $2}' | sort -n))
            tx_pps_avg=$(( ($(printf '%b + ' "${tx_pps_arr[@]}"\\c)) / ${#tx_pps_arr[@]} ))
        fi
    done

    echo "${dpdk_version},${test_mode},${core},${tx_pps_avg},${rx_pps_avg},${fwdtx_pps_avg}" >> ${testpmd_csv_file}
}

function run_testcase() {
    if [ -z "${CORES}" ]; then
        CORES="1"
        LogMsg "CORES not found in environment; doing default single core test"
    fi

    if [ -z "${TEST_DURATION}" ]; then
        TEST_DURATION=120
        LogMsg "TEST_DURATION not found in environment; using default ${TEST_DURATION}"
    fi

    if [ -z "${MODES}" ]; then
        MODES="rxonly fwd"
        LogMsg "MODES parameter not found in environment; using default ${MODES}"
    fi

    LogMsg "Starting testpmd execution"
    for core in ${CORES}; do
        run_testpmd ${core} "${MODES}" ${TEST_DURATION}
    done

    LogMsg "Starting testpmd parser execution"
    echo "dpdk_version,test_mode,core,tx_pps_avg,rx_pps_avg,fwdtx_pps_avg" > ${LIS_HOME}/dpdk_testpmd.csv
    for core in ${CORES}; do
        for test_mode in ${MODES}; do
            testpmd_parser ${core} ${test_mode} ${LIS_HOME}/dpdk_testpmd.csv
        done
    done

    LogMsg "testpmd results"
    column -s, -t ${LIS_HOME}/dpdk_testpmd.csv
}