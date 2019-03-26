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
#   - called by Install_Dpdk in dpdk top level dir
#   - first argument is install_ip
function Dpdk_Configure() {
	if [ -z "${1}" ]; then
		LogErr "ERROR: Must provide install_ip to Dpdk_Configure"
		SetTestStateAborted
		exit 1
	fi

	if [ "${1}" = "${sender}" ]; then
		local dpdk_ips_cmd="hostname -I"
		local sender_dpdk_ips=($(eval "${dpdk_ips_cmd}"))
		local receiver_dpdk_ips=($(ssh "${receiver}" "${dpdk_ips_cmd}"))

		Testpmd_Ip_Setup "SRC" "${sender_dpdk_ips[1]}"
		Testpmd_Ip_Setup "DST" "${receiver_dpdk_ips[1]}"

		Testpmd_Multiple_Tx_Flows_Setup
	fi
}

# Requires
#   - UtilsInit
#   - core, modes, and test_duration as arguments in that order
#   - LIS_HOME, LOG_DIR, and DPDK_DIR to be defined
#   - sender, receiver, and IP_ADDRS to be defined
function Run_Testpmd() {
	if [ -z "${1}" -o -z "${2}" -o -z "${3}" ]; then
		LogErr "ERROR: Must provide core, modes, test_duration as arguments in that order to Run_Testpmd()"
		SetTestStateAborted
		exit 1
	fi

	if [ -z "${LIS_HOME}" -o -z "${LOG_DIR}" -o -z "${DPDK_DIR}" ]; then
		LogErr "ERROR: LIS_HOME, LOG_DIR, and DPDK_DIR must be defined in environment"
		SetTestStateAborted
		exit 1
	fi

	if [ -z "${sender}" -o -z "${receiver}" -o -z "${IP_ADDRS}" ]; then
		LogErr "ERROR: sender, receiver, and IP_ADDRS must be defined by constants.sh"
		SetTestStateAborted
		exit 1
	fi

	local core=${1}
	local modes=${2}
	local test_duration=${3}

	for test_mode in ${modes}; do
		LogMsg "Ensuring free hugepages"
		local free_huge_cmd="rm -rf /dev/hugepages/*"
		for ip in $IP_ADDRS; do
			ssh "${ip}" "${free_huge_cmd}"
		done

		# start receiver in advance so traffic spike doesn't cause output freeze
		local receiver_duration=$(expr "${test_duration}" + 5)

		local receiver_testpmd_cmd="$(Create_Timed_Testpmd_Cmd "${receiver_duration}" "${core}" "${receiver_busaddr}" "${receiver_iface}" "${test_mode}")"
		LogMsg "${receiver_testpmd_cmd}"
		ssh "${receiver}" "${receiver_testpmd_cmd}" 2>&1 > "${LOG_DIR}"/dpdk-testpmd-"${test_mode}"-receiver-"${core}"-core-$(date +"%m%d%Y-%H%M%S").log &

		sleep 5

		local sender_testpmd_cmd="$(Create_Timed_Testpmd_Cmd "${test_duration}" "${core}" "${sender_busaddr}" "${sender_iface}" txonly)"
		LogMsg "${sender_testpmd_cmd}"
		eval "${sender_testpmd_cmd} 2>&1 > ${LOG_DIR}/dpdk-testpmd-${test_mode}-sender-${core}-core-$(date +"%m%d%Y-%H%M%S").log &"

		sleep "${test_duration}"

		LogMsg "killing testpmd"
		local kill_cmd="pkill testpmd"
		for ip in $IP_ADDRS; do
			ssh "${ip}" "${kill_cmd}"
		done

		LogMsg "TestPmd execution for ${test_mode} mode on ${core} core(s) is COMPLETED"
		sleep 10
	done
}

# Requires
#   - UtilsInit
#   - arguments in order: core, test_mode, csv file
#   - LOG_DIR to be defined
function Testpmd_Parser() {
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
	local dpdk_version=$(Get_DPDK_Version "${LIS_HOME}/${DPDK_DIR}")

	local log_files=$(ls "${LOG_DIR}"/*.log | grep "dpdk-testpmd-${test_mode}-.*-${core}-core")
	LogMsg "Parsing test run ${test_mode} mode ${core} core(s)"
	for file in ${log_files}; do
		LogMsg "  Reading ${file}"
		if [[ "${file}" =~ "receiver" ]]; then
			rx_pps_Max=$(cat "${file}" | grep Rx-pps: | awk '{print $2}' | sort -n | tail -1)
			rx_pps_arr=($(grep Rx-pps: "${file}" | awk '{print $2}' | sort -n))
			rx_pps_avg=$(( ($(printf '%b + ' "${rx_pps_arr[@]}"\\c)) / ${#rx_pps_arr[@]} ))
			rx_bytes_arr=($(cat  "${file}" | grep RX-bytes: | rev | awk '{print $1}' | rev))
			rx_bytes_avg=$(($(expr $(printf '%b + ' "${rx_bytes_arr[@]::${#rx_bytes_arr[@]}}"\\c))/${#rx_bytes_arr[@]}))
			rx_packets_arr=($(cat  "${file}" | grep RX-packets: | awk '{print $2}'))
			rx_packets_avg=$(($(expr $(printf '%b + ' "${rx_packets_arr[@]::${#rx_packets_arr[@]}}"\\c))/${#rx_packets_arr[@]}))

			fwdtx_pps_arr=($(grep Tx-pps: "${file}" | awk '{print $2}' | sort -n))
			fwdtx_pps_avg=$(( ($(printf '%b + ' "${fwdtx_pps_arr[@]}"\\c)) / ${#fwdtx_pps_arr[@]} ))
			fwdtx_bytes_arr=($(cat "${file}" | grep TX-bytes: | rev | awk '{print $1}' | rev))
			fwdtx_bytes_avg=$(($(expr $(printf '%b + ' "${fwdtx_bytes_arr[@]::${#fwdtx_bytes_arr[@]}}"\\c))/${#fwdtx_bytes_arr[@]}))
			fwdtx_packets_arr=($(cat "${file}" | grep TX-packets: | awk '{print $2}'))
			fwdtx_packets_avg=$(($(expr $(printf '%b + ' "${fwdtx_packets_arr[@]::${#fwdtx_packets_arr[@]}}"\\c))/${#fwdtx_packets_arr[@]}))
		elif [[ "${file}" =~ "sender" ]]; then
			tx_pps_arr=($(grep Tx-pps: "${file}" | awk '{print $2}' | sort -n))
			tx_pps_avg=$(( ($(printf '%b + ' "${tx_pps_arr[@]}"\\c)) / ${#tx_pps_arr[@]} ))
			tx_bytes_arr=($(cat "${file}" | grep TX-bytes: | rev | awk '{print $1}' | rev))
			tx_bytes_avg=$(($(expr $(printf '%b + ' "${tx_bytes_arr[@]::${#tx_bytes_arr[@]}}"\\c))/${#tx_bytes_arr[@]}))
			rx_packets_arr=($(cat "${file}" | grep TX-packets: | awk '{print $2}'))
			tx_packets_avg=$(($(expr $(printf '%b + ' "${rx_packets_arr[@]::${#rx_packets_arr[@]}}"\\c))/${#rx_packets_arr[@]}))
		fi
	done
	tx_packet_size=$((tx_bytes_avg/tx_packets_avg))
	rx_packet_size=$((rx_bytes_avg/rx_packets_avg))
	echo "${dpdk_version},${test_mode},${core},${rx_pps_Max},${tx_pps_avg},${rx_pps_avg},${fwdtx_pps_avg},${tx_bytes_avg},${rx_bytes_avg},${fwdtx_bytes_avg},${tx_packets_avg},${rx_packets_avg},${fwdtx_packets_avg},${tx_packet_size},${rx_packet_size}" >> "${testpmd_csv_file}"
}

function Run_Testcase() {
	if [ -z "${CORES}" ]; then
		CORES=(1)
		LogMsg "CORES not found in environment; doing default single core test"
	fi

	if [ -z "${TEST_DURATION}" ]; then
		TEST_DURATION=120
		LogMsg "TEST_DURATION not found in environment; using default ${TEST_DURATION}"
	fi

	if [ -z "${MODES}" ]; then
		MODES="rxonly io"
		LogMsg "MODES parameter not found in environment; using default ${MODES}"
	fi

	LogMsg "Starting testpmd"
	Create_Vm_Synthetic_Vf_Pair_Mappings
	for core in "${CORES[@]}"; do
		Run_Testpmd ${core} "${MODES}" ${TEST_DURATION}
	done

	LogMsg "Starting testpmd parser"
	local csv_file=$(Create_Csv)
	echo "dpdk_version,test_mode,core,max_rx_pps,tx_pps_avg,rx_pps_avg,fwdtx_pps_avg,tx_bytes,rx_bytes,fwd_bytes,tx_packets,rx_packets,fwd_packets,tx_packet_size,rx_packet_size" > "${csv_file}"
	for core in "${CORES[@]}"; do
		for test_mode in ${MODES}; do
			Testpmd_Parser ${core} "${test_mode}" "${csv_file}"
		done
	done

	LogMsg "testpmd results"
	column -s, -t "${csv_file}"
}