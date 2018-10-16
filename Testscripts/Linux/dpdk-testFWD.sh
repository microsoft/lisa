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
#   - called by install_dpdk in dpdk top level dir
#   - first argument is install_ip
function dpdk_configure() {
	if [ -z "${1}" ]; then
		LogErr "ERROR: Must provide install_ip to dpdk_configure"
		SetTestStateAborted
		exit 1
	fi

	local dpdk_ips_cmd="hostname -I"
	if [ "${1}" = "${sender}" ]; then
		local sender_dpdk_ips=($(eval ${dpdk_ips_cmd}))
		local forwarder_dpdk_ips=($(ssh ${forwarder} "${dpdk_ips_cmd}"))

		testpmd_ip_setup "SRC" "${sender_dpdk_ips[1]}"
		testpmd_ip_setup "DST" "${forwarder_dpdk_ips[1]}"

		local num_port_code="#define NUM_SRC_PORTS 8"
		local port_arr_code="static uint16_t src_ports[NUM_SRC_PORTS] = {200,300,400,500,600,700,800,900};"
		local port_code="pkt_udp_hdr.src_port = rte_cpu_to_be_16(src_ports[nb_pkt % NUM_SRC_PORTS]);"

		sed -i "54i ${num_port_code}" app/test-pmd/txonly.c
		sed -i "55i ${port_arr_code}" app/test-pmd/txonly.c
		sed -i "234i ${port_code}" app/test-pmd/txonly.c
	elif [ "${1}" = "${forwarder}" ]; then
		local receiver_dpdk_ips=($(ssh ${receiver} "${dpdk_ips_cmd}"))

		local ptr_code="struct ipv4_hdr *ipv4_hdr;"
		local offload_code="ol_flags |= PKT_TX_IP_CKSUM; ol_flags |= PKT_TX_IPV4;"
		local dst_addr=$(echo ${receiver_dpdk_ips[1]} | sed 'y/\./,/')
		local dst_addr_code="ipv4_hdr = rte_pktmbuf_mtod_offset(mb, struct ipv4_hdr *, sizeof(struct ether_hdr)); ipv4_hdr->dst_addr = rte_be_to_cpu_32(IPv4(${dst_addr}));"

		sed -i "53i ${ptr_code}" app/test-pmd/macfwd.c
		sed -i "90i ${offload_code}" app/test-pmd/macfwd.c
		sed -i "101i ${dst_addr_code}" app/test-pmd/macfwd.c
	fi
}

# Requires
#   - UtilsInit
#   - core and test_duration as arguments in that order
#   - LOG_DIR, IP_ADDRS, sender, forwarder, and receiver to be defined
function run_testfwd() {
	if [ -z "${1}" -o -z "${2}" ]; then
		LogErr "ERROR: Must provide core and test_duration as arguments in that order to run_testfwd()"
		SetTestStateAborted
		exit 1
	fi

	if [ -z "${LIS_HOME}" -o -z "${LOG_DIR}" ]; then
		LogErr "ERROR: LIS_HOME, LOG_DIR ust be defined in environment"
		SetTestStateAborted
		exit 1
	fi

	if [ -z "${sender}" -o -z "${forwarder}" -o -z "${receiver}" ]; then
		LogErr "ERROR: sender, forwarder, and receiver must be define by constants.sh"
		SetTestStateAborted
		exit 1
	fi

	local core=${1}
	local test_duration=${2}
	local dpdk_dir=$(ls ${LIS_HOME} | grep dpdk | grep -v \.sh)

	local ip
	LogMsg "Ensuring free hugepages"
	local free_huge_cmd="rm -rf /dev/hugepages/*"
	for ip in $IP_ADDRS; do
		ssh ${ip} ${free_huge_cmd}
	done
	
	# start receiver, fowarder in advance so testpmd comes up easily
	local fwd_recv_duration=$(expr ${test_duration} + 5)
	
	local receiver_testfwd_cmd="timeout ${fwd_recv_duration} ${LIS_HOME}/${dpdk_dir}/build/app/testpmd -l 0-${core} -w ${receiver_busaddr} --vdev='net_vdev_netvsc0,iface=${receiver_iface}' -- --port-topology=chained --nb-cores ${core} --txq ${core} --rxq ${core} --mbcache=512 --txd=4096 --rxd=4096 --forward-mode=rxonly --stats-period 1"
	LogMsg "${receiver_testfwd_cmd}"
	ssh ${receiver} ${receiver_testfwd_cmd} 2>&1 > ${LOG_DIR}/dpdk-testfwd-receiver-${core}-core-$(date +"%m%d%Y-%H%M%S").log &
 
	local forwarder_testfwd_cmd="timeout ${fwd_recv_duration} ${LIS_HOME}/${dpdk_dir}/build/app/testpmd -l 0-${core} -w ${forwarder_busaddr} --vdev='net_vdev_netvsc0,iface=${forwarder_iface}' -- --port-topology=chained --nb-cores ${core} --txq ${core} --rxq ${core} --mbcache=512 --txd=4096 --rxd=4096 --forward-mode=mac --stats-period 1 --tx-offloads=0x800e"
	LogMsg "${forwarder_testfwd_cmd}"
	ssh ${forwarder} ${forwarder_testfwd_cmd} 2>&1 > ${LOG_DIR}/dpdk-testfwd-forwarder-${core}-core-$(date +"%m%d%Y-%H%M%S").log &

	sleep 5
	
	local sender_testfwd_cmd="timeout ${test_duration} ${LIS_HOME}/${dpdk_dir}/build/app/testpmd -l 0-${core} -w ${sender_busaddr} --vdev='net_vdev_netvsc0,iface=${sender_iface}' -- --port-topology=chained --nb-cores ${core} --txq ${core} --rxq ${core} --mbcache=512 --txd=4096 --forward-mode=txonly --stats-period 1 2>&1 > ${LOG_DIR}/dpdk-testfwd-sender-${core}-core-$(date +"%m%d%Y-%H%M%S").log &"
	LogMsg "${sender_testfwd_cmd}"
	eval ${sender_testfwd_cmd}
	
	sleep ${test_duration}
	
	LogMsg "killing testpmd"
	local kill_cmd="pkill testpmd"
	for ip in $IP_ADDRS; do
		ssh ${ip} ${kill_cmd}
	done
	
	LogMsg "Testfwd execution for with ${core} core(s) is COMPLETED"
	sleep 10
}

# Requires
#   - UtilsInit
#   - arguments in order: core, csv file
#   - LOG_DIR to be defined
function testfwd_parser() {
	if [ -z "${1}" -o -z "${2}" ]; then
		LogErr "ERROR: Must provide core, and csv file in that order to testfwd_parser()"
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
	local dpdk_dir=$(ls ${LIS_HOME} | grep dpdk | grep -v \.sh | grep -v \.csv)
	local dpdk_version=$(grep "Version:" ${LIS_HOME}/${dpdk_dir}/pkg/dpdk.spec | awk '{print $2}')

	local log_files=$(ls ${LOG_DIR}/*.log | grep "dpdk-testfwd-.*-${core}-core")
	LogMsg "Parsing test run mode ${core} core(s)"
	for file in ${log_files}; do
		LogMsg "  Reading ${file}"
		if [[ "${file}" =~ "receiver" ]]; then
			local rx_pps_arr=($(grep Rx-pps: ${file} | awk '{print $2}' | sort -n))
			local rx_pps_avg=$(( ($(printf '%b + ' "${rx_pps_arr[@]}"\\c)) / ${#rx_pps_arr[@]} ))
		elif [[ "${file}" =~ "forwarder" ]]; then
			local fwdrx_pps_arr=($(grep Rx-pps: ${file} | awk '{print $2}' | sort -n))
			local fwdrx_pps_avg=$(( ($(printf '%b + ' "${fwdrx_pps_arr[@]}"\\c)) / ${#fwdrx_pps_arr[@]} ))

			local fwdtx_pps_arr=($(grep Tx-pps: ${file} | awk '{print $2}' | sort -n))
			local fwdtx_pps_avg=$(( ($(printf '%b + ' "${fwdtx_pps_arr[@]}"\\c)) / ${#fwdtx_pps_arr[@]} ))
		elif [[ "${file}" =~ "sender" ]]; then
			local tx_pps_arr=($(grep Tx-pps: ${file} | awk '{print $2}' | sort -n))
			local tx_pps_avg=$(( ($(printf '%b + ' "${tx_pps_arr[@]}"\\c)) / ${#tx_pps_arr[@]} ))
		fi
	done

	echo "${dpdk_version},${core},${tx_pps_avg},${fwdrx_pps_avg},${fwdtx_pps_avg},${rx_pps_avg}" >> ${testfwd_csv_file}
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

	if [ -z "${VM_NAMES}" ]; then
		LogErr "ERROR: VM_NAMES should be defined by constants.sh"
		SetTestStateAborted
		exit 1
	fi

	local name
	for name in $VM_NAMES; do
		local pairs=($(ssh ${!name} "$(typeset -f get_synthetic_vf_pairs); get_synthetic_vf_pairs"))
		if [ "${#pairs[@]}" -eq 0 ]; then
			LogErr "ERROR: No ${name} VFs present"
			SetTestStateFailed
			exit 1
		fi

		# set global if/busaddr pairs
		eval ${name}_iface="${pairs[0]}"
		eval ${name}_busaddr="${pairs[1]}"
	done

	LogMsg "Starting testfwd execution"
	for core in ${CORES}; do
		run_testfwd ${core} ${TEST_DURATION}
	done

	LogMsg "Starting testfwd parser"
	echo "dpdk_version,core,tx_pps_avg,fwdrx_pps_avg,fwdtx_pps_avg,rx_pps_avg" > ${LIS_HOME}/dpdk_testfwd.csv
	for core in ${CORES}; do
		LogMsg "Parsing dpdk fwd results for ${core} core mode"
		testfwd_parser ${core} ${LIS_HOME}/dpdk_testfwd.csv
	done

	LogMsg "testfwd results"
	column -s, -t ${LIS_HOME}/dpdk_testfwd.csv
}
