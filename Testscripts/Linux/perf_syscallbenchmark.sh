#!/bin/bash
#######################################################################
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
# perf_syscallbenchmark.sh
# Description:
#    Download and run syscall benchmark test.
# Supported Distros:
#    Ubuntu, SUSE, RedHat, CentOS
#######################################################################
HOMEDIR=$(pwd)
UTIL_FILE="./utils.sh"

. ${UTIL_FILE} || {
	echo "ERROR: unable to source utils.sh!"
	echo "TestAborted" > state.txt
	exit 2
}

# Source constants file and initialize most common variables
UtilsInit

LogMsg "Sleeping 10 seconds.."
sleep 10

run_syscall_benchmark()
{
	SetTestStateRunning
	#Syscall benchmark test start..
	LogMsg "git clone SysCall benchmark started..."
	git clone "$syscallurl"
	cd syscall-benchmark && ./compile.sh
	if [ $? -ne 0 ]; then
		LogMsg "Error: Syscall compile failed.."
		SetTestStateAborted
		exit 2
	else
		LogMsg "INFO: SysCall benchmark install SUCCESS"
	fi

	LogMsg "SysCall benchmark test started..."
	./bench.sh
	if [ $? -ne 0 ]; then
		LogMsg "Error: Syscall benchmark run failed.."
		SetTestStateFailed
		exit 3
	else
		LogMsg "INFO: SysCall benchmark test run SUCCESS"
	fi

	cp "$LOGDIR"/results.log "${HOMEDIR}"/
	compressedFileName="${HOMEDIR}/syscall-benchmark-$(date +"%m%d%Y-%H%M%S").tar.gz"
	LogMsg "INFO: Please wait...Compressing all results to ${compressedFileName}..."
	tar -cvzf "$compressedFileName"  "${HOMEDIR}"/*.txt "${HOMEDIR}"/*.log "$LOGDIR"/
	echo "Test logs are located at ${LOGDIR}"
	SetTestStateCompleted
}

########################################################
# Main body
########################################################
LogMsg "*********INFO: Starting test setup*********"
# HOMEDIR=$HOME
LOGDIR="${HOMEDIR}/syscall-benchmark"
if [ -d "$LOGDIR" ]; then
  mv "$HOMEDIR"/syscall-benchmark/ "$HOMEDIR"/syscall-benchmark-$(date +"%m%d%Y-%H%M%S")/
fi

cd "${HOMEDIR}"
#Install required packages for SysCall benchmark
packages=("gcc" "yasm" "git" "tar" "wget" "dos2unix")
case "$DISTRO_NAME" in
	oracle|rhel|centos)
		install_epel
		;;
	ubuntu|debian)
		update_repos
		;;
	suse|opensuse|sles)
		add_sles_network_utilities_repo
		;;
	*)
		echo "Unknown distribution"
		SetTestStateAborted
		exit 1
esac
install_package "${packages[@]}"

#Run SysCall benchmark test
LogMsg "*********INFO: Starting test execution*********"
run_syscall_benchmark
LogMsg "*********INFO: Script execution reach END. Completed !!!*********"