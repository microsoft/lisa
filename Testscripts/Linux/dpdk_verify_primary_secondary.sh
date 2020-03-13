#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

# This script will build DPDK and run primary/secondary processes tests.

HOMEDIR=$(pwd)
export RTE_SDK="${HOMEDIR}/dpdk"
export RTE_TARGET="x86_64-native-linuxapp-gcc"
# shellcheck disable=SC2034
UTIL_FILE="./utils.sh"
# shellcheck disable=SC2034
DPDK_UTIL_FILE="./dpdkUtils.sh"
EXAMPLES_DIR_ROOT="examples/multi_process"
EXAMPLES_DIR="${EXAMPLES_DIR_ROOT}/client_server_mp"

# Source utils.sh
. utils.sh || {
	echo "ERROR: unable to source utils.sh!"
	echo "TestAborted" > state.txt
	exit 0
}

# Source constants file and initialize most common variables
UtilsInit

function build_test_dpdk_primary_secondary () {
	SetTestStateRunning
	trap "echo TestAborted > state.txt; exit 0" TERM
	LogMsg "Configuring ${1} ${DISTRO_NAME} ${DISTRO_VERSION} for primary/secondary test..."

	ssh "${1}" "cd ${RTE_SDK} && RTE_SDK=${RTE_SDK} RTE_TARGET=${RTE_TARGET} make -C ${EXAMPLES_DIR_ROOT}"
	check_exit_status "cd ${RTE_SDK} && RTE_SDK=${RTE_SDK} RTE_TARGET=${RTE_TARGET} make -C ${EXAMPLES_DIR_ROOT}' on ${1}" "exit"

	vf_pairs=$(get_synthetic_vf_pairs)
	nics=$(echo "${vf_pairs}" | awk '{print $1}')
	for nic in $nics; do
		ssh "${1}" "ip link set dev ${nic} down"
		check_exit_status "ip link set dev ${nic} down' on ${1}" "exit"
	done

	whitelist_params=""
	pci_ids=$(echo "${vf_pairs}" | awk '{print $2}')
	for pci_id in $pci_ids; do
		pci_id=$(echo $pci_id | tr -d \' | tr -d \" | tr -d '\012\015')
		whitelist_params="${whitelist_params} -w ${pci_id}"
	done

	LogMsg "Whitelisted PCI ids: ${whitelist_params}"
	mp_server_log_file="./primary_secondary_server.log"
	LogMsg "${RTE_SDK}/${EXAMPLES_DIR}/mp_server/${RTE_TARGET}/mp_server -l0-1 -n4 $whitelist_params -- -p 0x14 -n2  2>&1 > $mp_server_log_file &"
	"${RTE_SDK}/${EXAMPLES_DIR}/mp_server/${RTE_TARGET}/mp_server" -l0-1 -n4 $whitelist_params -- -p 0x14 -n2  2>&1 > $mp_server_log_file &
	sleep 30
	mp_client_log_file="./primary_secondary.log"
	LogMsg "timeout --preserve-status 30 ${RTE_SDK}/${EXAMPLES_DIR}/mp_client/${RTE_TARGET}/mp_client -l3 \
		-n4 --proc-type=auto $whitelist_params -- -n 0 2>&1 > $mp_client_log_file"
	timeout --preserve-status 30 "${RTE_SDK}/${EXAMPLES_DIR}/mp_client/${RTE_TARGET}/mp_client" -l3 \
		-n4 --proc-type=auto $whitelist_params -- -n 0 2>&1 > $mp_client_log_file

	test_output=$(cat $mp_client_log_file)
	pkill -f mp_server
	if [[ "${test_output}" == *"Failed"* ]] || [[ "${test_output}" == *"Segmentation fault"* ]]; then
		LogErr "Test output failure: $test_output"
		SetTestStateFailed
		exit 0
	fi
	if [[ "${test_output}" == *"APP: Finished Process Init"* ]]; then
		SetTestStateCompleted
	fi
	LogMsg "Built and ran tests for primary/secondary on ${1} with output: $test_output"
}

LogMsg "Script execution started"
LogMsg "Starting build and tests for primary/secondary"

build_test_dpdk_primary_secondary "${client}"
LogMsg "primary/secondary build and test completed"

