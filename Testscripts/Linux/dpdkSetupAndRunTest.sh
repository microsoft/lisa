#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

#############################################################################
#
# dpdkSetupAndRunTest.sh
# Description:
#   This script is employed by DPDK-TEMPLATE.ps1 to set up dpdk and run
#   user provided test cases.
#
#############################################################################

function dpdk_setup() {
	if [ -z "${IP_ADDRS}" ]; then
		LogErr "ERROR: IP_ADDRS must be defined in environment"
		SetTestStateAborted
		exit 1
	fi

	local ip
	for ip in $IP_ADDRS; do
		Install_Dpdk "${ip}" > "${LIS_HOME}"/dpdk_"${ip}"_install.log 2>&1 &
		local pids="$pids $!"
	done
	for pid in $(echo "$pids");do
		wait "$pid"
	done

	for ip in $IP_ADDRS; do
		Hugepage_Setup "${ip}" &
		local pids="$pids $!"
	done
	for pid in $(echo "$pids");do
		wait "$pid"
		if [ $? -ne 0 ]; then
			LogErr "DPDK setup failed."
			SetTestStateAborted
			exit 1
		fi
	done

	for ip in $IP_ADDRS; do
		Modprobe_Setup "${ip}" &
		local pids="$pids $!"
	done
	for pid in $(echo "$pids");do
		wait "$pid"
		if [ $? -ne 0 ]; then
			LogErr "DPDK setup failed."
			SetTestStateAborted
			exit 1
		fi
	done
	sleep 2
}

# Requires:
#	- UtilsInit has been called
# 	- 1st argument is script to source
# Effects:
#	Sources script, if it cannot aborts test
function source_script() {
    if [ -z "${1}" ]; then
        LogErr "Must supply script name as 1st argument to sourceScript"
        SetTestStateAborted
        exit 1
    fi

    local file=${1}
    if [ -e ${file} ]; then
        source ${file}
    else
        LogErr "Failed to source ${file} file"
        SetTestStateAborted
        exit 1
    fi
}

# Source utils.sh
. utils.sh || {
	echo "ERROR: unable to source utils.sh!" | tee "${HOME}"/TestExecutionError.log
	echo "TestAborted" > "${HOME}"/state.txt
	exit 1
}

source_script "dpdkUtils.sh"

# Source constants file and initialize most common variables
UtilsInit
LOG_DIR="${LIS_HOME}/logdir"
rm -rf "${LOG_DIR}" # LISA Pipelines don't always wipe old state
mkdir -p "${LOG_DIR}"
PHASE_FILE="${LIS_HOME}/phase.txt"
> "${PHASE_FILE}"

# constants.sh is now loaded; load user provided scripts
for file in ${USER_FILES}; do
	source_script "${LIS_HOME}/${file}"
done

# error check here so on failure don't waste time setting up dpdk
if ! type Run_Testcase > /dev/null; then
	LogErr "ERROR: missing Run_Testcase function"
	SetTestStateAborted
	exit 1
fi

LogMsg "Starting DPDK Setup"
# when available update to dpdk latest
if [ -z "${dpdkSrcLink}" ]; then
	dpdkSrcLink="https://fast.dpdk.org/rel/dpdk-18.08.tar.xz"
	LogMsg "dpdkSrcLink missing from environment; using ${dpdkSrcLink}"
fi

# set DPDK_DIR global
DPDK_DIR="dpdk"

LogMsg "DPDK source dir is: ${DPDK_DIR}"

dpdk_setup
if [ $? -ne 0 ]; then
	LogErr "DPDK setup failed."
	SetTestStateAborted
	exit 1
fi

LogMsg "Calling testcase provided run function"
Run_Testcase

LogMsg "tar -cvzf ${LIS_HOME}/vmTestcaseLogs.tar.gz ${LOG_DIR}"
tar -cvzf "${LIS_HOME}"/vmTestcaseLogs.tar.gz "${LOG_DIR}"

LogMsg "dpdkSetupAndRunTest completed!"
SetTestStateCompleted
