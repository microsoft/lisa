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

		testpmd_multiple_tx_flows_setup
	elif [ "${1}" = "${forwarder}" ]; then
		local receiver_dpdk_ips=($(ssh ${receiver} "${dpdk_ips_cmd}"))
		testpmd_macfwd_to_dest "${receiver_dpdk_ips[1]}"
	fi
}

# Requires
#   - UtilsInit
#   - core and test_duration as arguments in that order
#   - LOG_DIR, IP_ADDRS, sender, forwarder, and receiver to be defined
function run_testfailsafe() {
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

	local core=8

	local ip
	LogMsg "Ensuring free hugepages"
	local free_huge_cmd="rm -rf /dev/hugepages/*"
	for ip in $IP_ADDRS; do
		ssh ${ip} ${free_huge_cmd}
	done
	
	local receiver_testfwd_cmd="$(create_testpmd_cmd ${core} ${receiver_busaddr} ${receiver_iface} rxonly)"
	LogMsg "${receiver_testfwd_cmd}"
	ssh ${receiver} ${receiver_testfwd_cmd} 2>&1 > ${LOG_DIR}/dpdk-testfailsafe-receiver.log &
 
	local forwarder_testfwd_cmd="$(create_testpmd_cmd ${core} ${forwarder_busaddr} ${forwarder_iface} mac)"
	LogMsg "${forwarder_testfwd_cmd}"
	ssh ${forwarder} ${forwarder_testfwd_cmd} 2>&1 > ${LOG_DIR}/dpdk-testfailsafe-forwarder.log &

	sleep 5
	
	local sender_testfwd_cmd="$(create_testpmd_cmd ${core} ${sender_busaddr} ${sender_iface} txonly)"
	# reduce txd so VF revoke doesn't kill forwarder
	sender_testfwd_cmd=$(echo ${sender_testfwd_cmd} | sed -r 's,(--.xd=)4096,\110,')
	LogMsg "${sender_testfwd_cmd}"
	eval "${sender_testfwd_cmd} 2>&1 > ${LOG_DIR}/dpdk-testfailsafe-sender.log &"
	
	lost_vf_output="sub_device . probe failed"

	sleep 10
	# testpmd is has now run for 10 request testcase driver to revoke VF
	local ready_for_revoke_msg="READY_FOR_REVOKE"
	LogMsg ${ready_for_revoke_msg}
	update_phase ${ready_for_revoke_msg}

	# wait till revoke is done
	local phase
	while true; do
		phase="$(read_phase)"
		if [[ "${phase}" == "REVOKE_DONE" ]]; then
			sleep 10
			break
		fi
	done

	# vf was revoked for >= 10. now ready for it to be re-enabled
	local ready_for_vf_msg="READY_FOR_VF"
	LogMsg ${ready_for_vf_msg}
	update_phase ${ready_for_vf_msg}
	while true; do
		phase="$(read_phase)"
		if [[ "${phase}" == "VF_RE_ENABLED" ]]; then
			sleep 10
			# vf has been re-enabled for >=10 seconds now
			break
		fi
	done
	
	LogMsg "killing testpmd"
	local kill_cmd="pkill testpmd"
	for ip in $IP_ADDRS; do
		ssh ${ip} ${kill_cmd}
	done
	
	LogMsg "Testfailsafe execution is COMPLETED"
}

# Requires
#   - UtilsInit
#   - arguments in order: core, csv file
#   - LOG_DIR to be defined
function testfwd_parser() {
	if [ -z "${1}" ]; then
		LogErr "ERROR: Must provide csv file to testfwd_parser()"
		SetTestStateAborted
		exit 1
	fi

	if [ -z "${LOG_DIR}" ]; then
		LogErr "ERROR: LOG_DIR must be defined"
		SetTestStateAborted
		exit 1
	fi

	local testfwd_csv_file=${1}
	local dpdk_version=$(grep "Version:" ${LIS_HOME}/${DPDK_DIR}/pkg/dpdk.spec | awk '{print $2}')

	local log_files=$(ls ${LOG_DIR}/*.log | grep "dpdk-testfailsafe-")
	LogMsg "Parsing testfailsafe"
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

	echo "${dpdk_version},${tx_pps_avg},${fwdrx_pps_avg},${fwdtx_pps_avg},${rx_pps_avg}" >> ${testfwd_csv_file}
}

function run_testcase() {
	LogMsg "Starting testfailsafe"
	create_vm_synthetic_vf_pair_mappings
	run_testfailsafe

	LogMsg "Starting testfailsafe parser"
	local csv_name=$(create_csv)
	echo "dpdk_version,tx_pps_avg,fwdrx_pps_avg,fwdtx_pps_avg,rx_pps_avg" > ${csv_name}
	testfwd_parser ${csv_name}

	LogMsg "testfailsafe results"
	column -s, -t ${csv_name}
}
