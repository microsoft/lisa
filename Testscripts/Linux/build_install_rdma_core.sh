#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

# This script will build and install rdma-core

HOMEDIR=$(pwd)
UTIL_FILE="./utils.sh"
DPDK_UTIL_FILE="./dpdkUtils.sh"
# Source utils.sh
. utils.sh || {
	echo "ERROR: unable to source utils.sh!"
	echo "TestAborted" > state.txt
	exit 0
}

# Source constants file and initialize most common variables
UtilsInit

function build_install_rdma_core () {
	SetTestStateRunning
	packages=()
	case "${DISTRO_NAME}" in
		ubuntu|debian)
			ssh "${1}" ". ${UTIL_FILE} && update_repos && . ${DPDK_UTIL_FILE} && Install_Dpdk_Dependencies ${1} ${DISTRO_NAME}"
			packages=(devscripts equivs python-docutils cython3 pandoc python3-dev)
			;;
		*)
			echo "Unsupported distro ${DISTRO_NAME}"
			SetTestStateSkipped
			exit 0
	esac
	ssh "${1}" ". ${UTIL_FILE} && CheckInstallLockUbuntu && install_package ${packages[@]}"

	sed -i '/deb-src/s/^# //' /etc/apt/sources.list && apt update
	check_exit_status "enabled apt sources on ${1}" "exit"

	mk-build-deps rdma-core --install --tool "apt-get -o Debug::pkgProblemResolver=yes --no-install-recommends -y"
	check_exit_status "enabled apt sources on ${1}" "exit"

	RDMA_CORE_DIR="rdma-core"
	LogMsg "Remove folder $RDMA_CORE_DIR if exists."
	rm -rf "${RDMA_CORE_DIR}"
	git clone "${dpdkRdmaCoreSrcLink}" -b "${dpdkRdmaCoreBranch}" "${RDMA_CORE_DIR}"
	check_exit_status "git clone ${dpdkRdmaCoreSrcLink} rdma-core on ${1}" "exit"
	pushd "${RDMA_CORE_DIR}"
	debuild -i -uc -us -b --lintian-opts --profile debian
	check_exit_status "debuild -i -uc -us -b --lintian-opts --profile debian on ${1}" "exit"
	popd

	pushd "${HOMEDIR}"
	LogMsg "Install all built packages."
	dpkg -i *.deb
	check_exit_status "dpkg -i *.deb on ${1}" "exit"
	popd
}


LogMsg "Script execution started"
LogMsg "Starting build and install for rdma-core"

build_install_rdma_core "${client}"

SetTestStateCompleted
LogMsg "Build and install for rdma-core completed"

