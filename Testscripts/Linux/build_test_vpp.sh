#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

# This script will build and test VPP.

HOMEDIR=$(pwd)
export VPP_DIR="${HOMEDIR}/vpp"
export RTE_SDK="${HOMEDIR}/dpdk"
export RTE_TARGET="x86_64-native-linuxapp-gcc"
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

function build_test_vpp () {
	SetTestStateRunning
	LogMsg "Configuring ${1} ${DISTRO_NAME} ${DISTRO_VERSION} for VPP test..."
	packages=(git)
	package_manager=""
	package_manager_install_flags=""
	package_type=""
	distro="${DISTRO_NAME}${DISTRO_VERSION}"
	case "${DISTRO_NAME}" in
		oracle|rhel|centos)
			package_manager="rpm"
			package_manager_install_flags="-ivh"
			package_type="rpm"
			ssh "${1}" ". ${UTIL_FILE} && install_epel"
			ssh "${1}" "yum -y --nogpgcheck groupinstall 'Development Tools'"
			check_exit_status "Install Development Tools on ${1}" "exit"
			ssh "${1}" ". ${UTIL_FILE} && . ${DPDK_UTIL_FILE} && Install_Dpdk_Dependencies ${1} ${distro}"
			packages=(kernel-devel-$(uname -r) librdmacm-devel redhat-lsb glibc-static \
				apr-devel numactl-devel.x86_64 libmnl-devel \
				check check-devel boost boost-devel selinux-policy selinux-policy-devel \
				ninja-build libuuid-devel mbedtls-devel yum-utils openssl-devel python-devel \
				python36-ply python36-devel python36-pip python-virtualenv devtoolset-7 \
				cmake3 asciidoc libffi-devel chrpath e2fsprogs-debuginfo glibc-debuginfo \
				krb5-debuginfo nss-softokn-debuginfo openssl-debuginfo \
				yum-plugin-auto-update-debug-info zlib-debuginfo python-ply java-1.8.0-openjdk-devel)
			;;
		ubuntu|debian)
			package_manager="dpkg"
			package_manager_install_flags="-i"
			package_type="deb"
			ssh "${1}" ". ${UTIL_FILE} && . ${DPDK_UTIL_FILE} && Install_Dpdk_Dependencies ${1} ${distro}"
			packages=(python-cffi python-pycparser)
			;;
		*)
			echo "Unsupported distro ${DISTRO_NAME}"
			SetTestStateSkipped
			exit 0
	esac
	ssh "${1}" ". ${UTIL_FILE} && CheckInstallLockUbuntu && install_package ${packages[@]}"

	if [[ $vppSrcLink =~ ".git" ]] || [[ $vppSrcLink =~ "git:" ]];
	then
		LogMsg "Installing from git repo ${vppSrcLink} to ${VPP_DIR}"
		ssh "${1}" git clone --recurse-submodules --single-branch --branch "${vppSrcBranch}" "${vppSrcLink}" "${VPP_DIR}"
		check_exit_status "git clone --recurse-submodules --single-branch --branch ${vppSrcBranch} ${vppSrcLink} on ${1}" "exit"
	else
		LogMsg "Provide proper link $vppSrcLink"
	fi

	# Build VPP using its own DPDK
	ssh "${1}" "cd ${VPP_DIR} && sed -i '/[^#]/ s/\(^.*centos-release-scl-rh.*$\)/#\ \1/' Makefile"
	ssh "${1}" ". ${UTIL_FILE} && cd ${VPP_DIR} && CheckInstallLockUbuntu && UNATTENDED=y make install-dep"
	check_exit_status "Installed dependencies on ${1}" "exit"

	ssh "${1}" "cd ${VPP_DIR} && sed -i '/vpp_uses_dpdk_mlx5_pmd/s/^# //g' build-data/platforms/vpp.mk"
	ssh "${1}" "cd ${VPP_DIR} && sed -i '/vpp_uses_dpdk_mlx4_pmd/s/^# //g' build-data/platforms/vpp.mk"

	ssh "${1}" "cd ${VPP_DIR} && make pkg-${package_type} vpp_uses_dpdk_mlx4_pmd=yes vpp_uses_dpdk_mlx5_pmd=yes DPDK_MLX4_PMD=y DPDK_MLX5_PMD=y DPDK_MLX5_PMD_DLOPEN_DEPS=y DPDK_MLX4_PMD_DLOPEN_DEPS=y"
	check_exit_status "make pkg-${package_type} vpp_uses_dpdk_mlx4_pmd=yes vpp_uses_dpdk_mlx5_pmd=yes DPDK_MLX4_PMD=y DPDK_MLX5_PMD=y DPDK_MLX5_PMD_DLOPEN_DEPS=y DPDK_MLX4_PMD_DLOPEN_DEPS=y on ${1}" "exit"

	prepare_install_command=". ${UTIL_FILE} && CheckInstallLockUbuntu && cd ${VPP_DIR} && ${package_manager} ${package_manager_install_flags}"
	ssh "${1}" "${prepare_install_command} build-root/*.${package_type}"
	if [[ $DISTRO_NAME = "ubuntu" ]]; then
		ssh "${1}" "apt --fix-broken -y install"
	fi
	check_exit_status "${prepare_install_command} build-root/*.${package_type} on ${1}" "exit"

	ssh "${1}" "modprobe uio_hv_generic"
	check_exit_status "modprobe uio_hv_generic on ${1}" "exit"

	pci_whitelist=$(get_synthetic_vf_pairs | sed "s/.* /dev /g")

	# Put down network interfaces, so that they can be bound to uio_hv_generic
	nics=$(get_synthetic_vf_pairs | awk '{print $1}')
	for nic in $nics
	do
		ip link set dev "${nic}" down
	done

	vpp_conf_file="/etc/vpp/startup.conf"
	echo "dpdk { ${pci_whitelist[@]} }" >> $vpp_conf_file
	ssh "${1}" "vpp -c ${vpp_conf_file}" &
	# Wait for VPP process to initialize
	sleep 10

	# VPP Azure interfaces show as fortygigabit interfaces
	vpp_hardware=$(ssh "${1}" vppctl show int | grep -iv 'local' | grep -E 'GigabitEthernet|VirtualFunctionEthernet')
	if [[ "${vpp_hardware}" != "" ]]; then
		LogMsg "VPP interfaces found: ${vpp_hardware[@]}"
		SetTestStateCompleted
	else
		LogErr "VPP interfaces not found."
		SetTestStateFailed
	fi

	LogMsg "Built and ran tests for VPP on ${1}"
}


LogMsg "Script execution started"

LogMsg "Starting build and tests for VPP"
build_test_vpp "${client}"
LogMsg "VPP build and test completed"

