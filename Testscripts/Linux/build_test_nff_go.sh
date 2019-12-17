#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

# This script will build and test NFF-GO.

HOMEDIR=$(pwd)
export NFF_GO_DIR="${HOMEDIR}/nff-go"
export DPDK_DIR="${HOMEDIR}/dpdk"
export RTE_SDK_DIR="${NFF_GO_DIR}/dpdk"
export RTE_SDK="${RTE_SDK_DIR}/dpdk"
export RTE_TARGET="x86_64-native-linuxapp-gcc"
UTIL_FILE="./utils.sh"

# Source utils.sh
. utils.sh || {
	echo "ERROR: unable to source utils.sh!"
	echo "TestAborted" > state.txt
	exit 0
}

# Source constants file and initialize most common variables
UtilsInit

function build_test_nff_go () {
	SetTestStateRunning
	LogMsg "Configuring ${1} ${DISTRO_NAME} ${DISTRO_VERSION} for NFF-GO test..."
	packages=(make git curl wget libpcap-dev libelf-dev hugepages libnuma-dev libhyperscan-dev liblua5.3-dev libmnl-dev libibverbs-dev)
	case "${DISTRO_NAME}" in
		ubuntu|debian)
			ssh "${1}" "until dpkg --force-all --configure -a; sleep 10; do echo 'Trying again...'; done"
			ssh "${1}" ". ${UTIL_FILE} && update_repos"
			;;
		*)
			echo "Unsupported distro ${DISTRO_NAME}"
			SetTestStateSkipped
			exit 0
	esac
	ssh "${1}" ". ${UTIL_FILE} && install_package ${packages[@]}"

	if [[ $nffGoSrcLink =~ ".git" ]] || [[ $nffGoSrcLink =~ "git:" ]];
	then
		LogMsg "Installing from git repo ${nffGoSrcLink} to ${NFF_GO_DIR}"
		ssh "${1}" git clone --recurse-submodules --single-branch --branch "${nffGoSrcBranch}" "${nffGoSrcLink}" "${NFF_GO_DIR}"
		check_exit_status "git clone --recurse-submodules --single-branch --branch ${nffGoSrcBranch} ${nffGoSrcLink} on ${1}" "exit"
		ssh "${1}" rm -rf "${RTE_SDK}"
		ssh "${1}" mv "${DPDK_DIR}" "${RTE_SDK_DIR}"
		check_exit_status "mv ${DPDK_DIR} ${RTE_SDK} on ${1}" "exit"
	else
		LogMsg "Provide proper link $nffGoSrcLink"
	fi

	ssh "${1}" "pushd /opt && curl -L -s ${nffGoEnvSrcLink} | tar zx"
	check_exit_status "GO env downloaded from ${nffGoEnvSrcLink} on ${1}" "exit"

	# Build NFF-GO using prebuilt DPDK
	exported_vars="RTE_SDK=${RTE_SDK} RTE_TARGET=${RTE_TARGET} GOROOT=/opt/go GOPATH=/tmp/go-fork PATH=\$GOROOT/bin:$GOPATH/bin:\$PATH"
	ssh "${1}" "cd ${NFF_GO_DIR} && eval '${exported_vars} go mod download'"
	check_exit_status "cd ${NFF_GO_DIR} && eval '${exported_vars} go mod download' on ${1}" "exit"
	ssh "${1}" "cd ${NFF_GO_DIR} && eval '${exported_vars} make -j'"
	check_exit_status "cd ${NFF_GO_DIR} && eval '${exported_vars} make -j on ${1}" "exit"
	ssh "${1}" "cd ${NFF_GO_DIR}/examples && eval '${exported_vars} make -j gopacketParserExample'"
	ssh "${1}" "cd ${NFF_GO_DIR}/examples && eval '${exported_vars} make -j nffPktgen'"
	ssh "${1}" "cd ${NFF_GO_DIR} && eval '${exported_vars} make -j -C examples/dpi'"

	# Start NFF-GO tests
	ssh "${1}" "cd ${NFF_GO_DIR} && eval '${exported_vars} make citesting'"
	check_exit_status "make citesting on ${1}" "exit"

	LogMsg "Built and ran tests for NFF-GO on ${1}"
}


LogMsg "Script execution Started"

LogMsg "Starting build and tests for NFF-GO"
build_test_nff_go "${client}"

SetTestStateCompleted
LogMsg "NFF-GO build and test completed"
