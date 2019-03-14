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
function Run_Testfailsafe() {
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
		ssh "${ip}" "${free_huge_cmd}"
	done
	
	local receiver_testfwd_cmd="$(Create_Testpmd_Cmd ${core} "${receiver_busaddr}" "${receiver_iface}" rxonly)"
	LogMsg "${receiver_testfwd_cmd}"
	ssh "${receiver}" "${receiver_testfwd_cmd}" 2>&1 > "${LOG_DIR}"/dpdk-testfailsafe-receiver.log &
 
	local forwarder_testfwd_cmd="$(Create_Testpmd_Cmd ${core} "${forwarder_busaddr}" "${forwarder_iface}" mac)"
	LogMsg "${forwarder_testfwd_cmd}"
	ssh "${forwarder}" "${forwarder_testfwd_cmd}" 2>&1 > "${LOG_DIR}"/dpdk-testfailsafe-forwarder.log &

	sleep 5
	
	local sender_testfwd_cmd="$(Create_Testpmd_Cmd ${core} "${sender_busaddr}" "${sender_iface}" txonly)"
	# reduce txd so VF revoke doesn't kill forwarder
	sender_testfwd_cmd=$(echo "${sender_testfwd_cmd}" | sed -r 's,(--.xd=)4096,\110,')
	LogMsg "${sender_testfwd_cmd}"
	eval "${sender_testfwd_cmd} 2>&1 > ${LOG_DIR}/dpdk-testfailsafe-sender.log &"
	

	sleep 120
	# testpmd is has now run for 120 request testcase driver to revoke VF
	local ready_for_revoke_msg="READY_FOR_REVOKE"
	Update_Phase ${ready_for_revoke_msg}
	local phase
	while true; do
		phase="$(Read_Phase)"
		if [ "${phase}" = "REVOKE_DONE" ]; then
			LogMsg "Phase changed to ${phase}"
			sleep 120
			break
		fi
	done

	# vf was revoked for >= 120. now ready for it to be re-enabled
	local ready_for_vf_msg="READY_FOR_VF"
	Update_Phase ${ready_for_vf_msg}
	while true; do
		phase="$(Read_Phase)"
		if [ "${phase}" = "VF_RE_ENABLED" ]; then
			LogMsg "Phase changed to ${phase}"
			sleep 120
			break
		fi
	done
	
	LogMsg "killing testpmd"
	local kill_cmd="pkill testpmd"
	for ip in $IP_ADDRS; do
		ssh "${ip}" "${kill_cmd}"
	done
	
	LogMsg "Testfailsafe execution is COMPLETED"
}

# Requires
#   - UtilsInit
#   - arguments in order: core, csv file
#   - LOG_DIR to be defined
function Testfailsafe_Parser() {
	if [ -z "${LOG_DIR}" ]; then
		LogErr "ERROR: LOG_DIR must be defined"
		SetTestStateAborted
		exit 1
	fi

	local csv_file=$(Create_Csv)
	echo "dpdk_version,phase,fwdrx_pps_avg,fwdtx_pps_avg" > "${csv_file}"
	local dpdk_version=$(Get_DPDK_Version "${LIS_HOME}/${DPDK_DIR}")

	local trimmed_prefix="trimmed-forwarder"
	local trimmed_log="${LOG_DIR}/${trimmed_prefix}.log"
	tail -n +11 "${LOG_DIR}"/dpdk-testfailsafe-forwarder.log > "${trimmed_log}"

	sed -e '/device removal event/,$d' "${trimmed_log}" > "${LOG_DIR}"/${trimmed_prefix}-before-revoke.log
	sed -e '1,/device removal event/d' "${trimmed_log}" | sed -e '/EAL:.*probe driver:.*net_mlx./,$d' > "${LOG_DIR}"/${trimmed_prefix}-during-revoke.log
	sed -e '1,/EAL:.*probe driver:.*net_mlx./d' "${trimmed_log}" > "${LOG_DIR}"/${trimmed_prefix}-after-enable.log

	local log_files=$(ls "${LOG_DIR}"/*.log | grep "${trimmed_prefix}")
	LogMsg "Parsing testfailsafe"
	for file in ${log_files}; do
		LogMsg "  Reading ${file}"

		local fwdrx_pps_arr=($(grep Rx-pps: "${file}" | awk '{print $2}'))
		local fwdrx_pps_avg=$(( ($(printf '%b + ' "${fwdrx_pps_arr[@]}"\\c)) / ${#fwdrx_pps_arr[@]} ))

		local fwdtx_pps_arr=($(grep Tx-pps: "${file}" | awk '{print $2}'))
		local fwdtx_pps_avg=$(( ($(printf '%b + ' "${fwdtx_pps_arr[@]}"\\c)) / ${#fwdtx_pps_arr[@]} ))

		local phase
		if [[ "${file}" =~ "before" ]]; then
			phase="before"
		elif [[ "${file}" =~ "during" ]]; then
			phase="during"
		elif [[ "${file}" =~ "after" ]]; then
			phase="after"
		else
			phase="overall"
		fi
		echo "${dpdk_version},${phase},${fwdrx_pps_avg},${fwdtx_pps_avg}" >> "${csv_file}"
	done

	column -s, -t "${csv_file}"
}

function Run_Testcase() {
	LogMsg "Starting testfailsafe"
	Create_Vm_Synthetic_Vf_Pair_Mappings
	Run_Testfailsafe

	LogMsg "Starting testfailsafe parser"
	Testfailsafe_Parser
}
