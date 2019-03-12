#!/bin/bash
#
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

#############################################################################
#
# dpdk-testFWD.sh
# Description:
#	This script runs testpmd with 3 VMs to measure performance in a more realistic
# 	forwaring scenario (i.e. a more correct packet stream that avoids the exception path).
#	It places testpmd output in $LOG_DIR, and then parses output to calculate avg pps.
#	The accompanying ps1 script makes sure testpmd performs above the expected threshold.
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

	local dpdk_ips_cmd="hostname -I"
	if [ "${1}" = "${sender}" ]; then
		local sender_dpdk_ips=($(eval "${dpdk_ips_cmd}"))
		local forwarder_dpdk_ips=($(ssh "${forwarder}" "${dpdk_ips_cmd}"))

		Testpmd_Ip_Setup "SRC" "${sender_dpdk_ips[1]}"
		Testpmd_Ip_Setup "DST" "${forwarder_dpdk_ips[1]}"

		Testpmd_Multiple_Tx_Flows_Setup
	elif [ "${1}" = "${forwarder}" ]; then
		local receiver_dpdk_ips=($(ssh "${receiver}" "${dpdk_ips_cmd}"))
		Testpmd_Macfwd_To_Dest "${receiver_dpdk_ips[1]}"
	fi
}

# Requires
#   - UtilsInit
#   - core and test_duration as arguments in that order
#   - LOG_DIR, IP_ADDRS, sender, forwarder, and receiver to be defined
function Run_Testfwd() {
	if [ -z "${1}" -o -z "${2}" ]; then
		LogErr "ERROR: Must provide core and test_duration as arguments in that order to Run_Testfwd()"
		SetTestStateAborted
		exit 1
	fi

	if [ -z "${LIS_HOME}" -o -z "${LOG_DIR}" -o -z "${DPDK_DIR}" ]; then
		LogErr "ERROR: LIS_HOME, LOG_DIR, and DPDK_DIR must be defined in environment"
		SetTestStateAborted
		exit 1
	fi

	if [ -z "${sender}" -o -z "${forwarder}" -o -z "${receiver}" -o -z "${IP_ADDRS}" ]; then
		LogErr "ERROR: sender, forwarder, receiver, and IP_ADDRS must be defined by constants.sh"
		SetTestStateAborted
		exit 1
	fi

	local core=${1}
	local test_duration=${2}

	local ip
	LogMsg "Ensuring free hugepages"
	local free_huge_cmd="rm -rf /dev/hugepages/*"
	for ip in $IP_ADDRS; do
		ssh "${ip}" "${free_huge_cmd}"
	done
	
	# start receiver and fowarder in advance so testpmd comes up easily
	local fwd_recv_duration=$(expr "${test_duration}" + 5)
	
	local receiver_testfwd_cmd="$(Create_Timed_Testpmd_Cmd "${fwd_recv_duration}" "${core}" "${receiver_busaddr}" "${receiver_iface}" rxonly)"
	LogMsg "${receiver_testfwd_cmd}"
	ssh "${receiver}" "${receiver_testfwd_cmd}" 2>&1 > "${LOG_DIR}"/dpdk-testfwd-receiver-"${core}"-core-$(date +"%m%d%Y-%H%M%S").log &
 
	local forwarder_testfwd_cmd="$(Create_Timed_Testpmd_Cmd "${fwd_recv_duration}" "${core}" "${forwarder_busaddr}" "${forwarder_iface}" mac)"
	LogMsg "${forwarder_testfwd_cmd}"
	ssh "${forwarder}" "${forwarder_testfwd_cmd}" 2>&1 > "${LOG_DIR}"/dpdk-testfwd-forwarder-"${core}"-core-$(date +"%m%d%Y-%H%M%S").log &

	sleep 5
	
	local sender_testfwd_cmd="$(Create_Timed_Testpmd_Cmd "${test_duration}" "${core}" "${sender_busaddr}" "${sender_iface}" txonly)"
	LogMsg "${sender_testfwd_cmd}"
	eval "${sender_testfwd_cmd} 2>&1 > ${LOG_DIR}/dpdk-testfwd-sender-${core}-core-$(date +"%m%d%Y-%H%M%S").log &"
	
	sleep "${test_duration}"
	
	LogMsg "killing testpmd"
	local kill_cmd="pkill testpmd"
	for ip in $IP_ADDRS; do
		ssh "${ip}" "${kill_cmd}"
	done
	
	LogMsg "Testfwd execution for with ${core} core(s) is COMPLETED"
	sleep 10
}

# Requires
#   - UtilsInit
#   - arguments in order: core, csv file
#   - LOG_DIR to be defined
function Testfwd_Parser() {
	if [ -z "${1}" -o -z "${2}" ]; then
		LogErr "ERROR: Must provide core, and csv file in that order to Testfwd_Parser()"
		SetTestStateAborted
		exit 1
	fi

	if [ -z "${LOG_DIR}" ]; then
		LogErr "ERROR: LOG_DIR must be defined"
		SetTestStateAborted
		exit 1
	fi

	local core=${1}
	local testfwd_csv_file=${2}
	local dpdk_version=$(Get_DPDK_Version "${LIS_HOME}/${DPDK_DIR}")

	local log_files=$(ls "${LOG_DIR}"/*.log | grep "dpdk-testfwd-.*-${core}-core")
	LogMsg "Parsing test fwd ${core} core(s)"
	for file in ${log_files}; do
		LogMsg "  Reading ${file}"
		if [[ "${file}" =~ "receiver" ]]; then
			local rx_pps_arr=($(grep Rx-pps: "${file}" | awk '{print $2}'))
			local rx_pps_avg=$(( ($(printf '%b + ' "${rx_pps_arr[@]}"\\c)) / ${#rx_pps_arr[@]} ))
		elif [[ "${file}" =~ "forwarder" ]]; then
			local fwdrx_pps_arr=($(grep Rx-pps: "${file}" | awk '{print $2}'))
			local fwdrx_pps_avg=$(( ($(printf '%b + ' "${fwdrx_pps_arr[@]}"\\c)) / ${#fwdrx_pps_arr[@]} ))

			local fwdtx_pps_arr=($(grep Tx-pps: "${file}" | awk '{print $2}'))
			local fwdtx_pps_avg=$(( ($(printf '%b + ' "${fwdtx_pps_arr[@]}"\\c)) / ${#fwdtx_pps_arr[@]} ))
		elif [[ "${file}" =~ "sender" ]]; then
			local tx_pps_arr=($(grep Tx-pps: "${file}" | awk '{print $2}'))
			local tx_pps_avg=$(( ($(printf '%b + ' "${tx_pps_arr[@]}"\\c)) / ${#tx_pps_arr[@]} ))
		fi
	done

	echo "${dpdk_version},${core},${tx_pps_avg},${fwdrx_pps_avg},${fwdtx_pps_avg},${rx_pps_avg}" >> "${testfwd_csv_file}"
}

function Run_Testcase() {
	if [ -z "${CORES}" ]; then
		CORES="1"
		LogMsg "CORES not found in environment; doing default single core test"
	fi

	if [ -z "${TEST_DURATION}" ]; then
		TEST_DURATION=120
		LogMsg "TEST_DURATION not found in environment; using default ${TEST_DURATION}"
	fi

	LogMsg "Starting testfwd"
	Create_Vm_Synthetic_Vf_Pair_Mappings
	for core in ${CORES}; do
		Run_Testfwd ${core} ${TEST_DURATION}
	done

	LogMsg "Starting testfwd parser"
	local csv_file=$(Create_Csv)
	echo "dpdk_version,core,tx_pps_avg,fwdrx_pps_avg,fwdtx_pps_avg,rx_pps_avg" > "${csv_file}"
	for core in ${CORES}; do
		Testfwd_Parser ${core} "${csv_file}"
	done

	LogMsg "testfwd results"
	column -s, -t "${csv_file}"
}
