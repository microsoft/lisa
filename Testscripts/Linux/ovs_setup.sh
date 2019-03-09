#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

# This script will do setup huge pages
# and OVS installation on client and server machines.

HOMEDIR=$(pwd)
export RTE_SDK="${HOMEDIR}/dpdk"
export RTE_TARGET="x86_64-native-linuxapp-gcc"
export OVS_DIR="${HOMEDIR}/ovs"
UTIL_FILE="./utils.sh"

# Source utils.sh
. utils.sh || {
	echo "ERROR: unable to source utils.sh!"
	echo "TestAborted" > state.txt
	exit 0
}

# Source constants file and initialize most common variables
UtilsInit

function install_ovs () {
	SetTestStateRunning
	LogMsg "Configuring ${1} ${DISTRO_NAME} ${DISTRO_VERSION} for OVS test..."
	packages=(gcc make git tar wget dos2unix psmisc make iperf3)
	case "${DISTRO_NAME}" in
		ubuntu|debian)
			ssh "${1}" "until dpkg --force-all --configure -a; sleep 10; do echo 'Trying again...'; done"
			ssh "${1}" ". ${UTIL_FILE} && update_repos"
			packages+=(autoconf libtool)
			;;
		*)
			echo "Unknown distribution"
			SetTestStateAborted
			exit 1
	esac
	ssh "${1}" ". ${UTIL_FILE} && install_package ${packages[@]}"

	if [[ $ovsSrcLink =~ .tar ]];
	then
		ovsSrcTar="${ovsSrcLink##*/}"
		ovsVersion=$(echo "$ovsSrcTar" | grep -Po "(\d+\.)+\d+")
		LogMsg "Installing OVS from source file $ovsSrcTar"
		ssh "${1}" "wget $ovsSrcLink -P /tmp"
		ssh "${1}" "tar xf /tmp/$ovsSrcTar"
		check_exit_status "tar xf /tmp/$ovsSrcTar on ${1}" "exit"
		ovsSrcDir="${ovsSrcTar%%".tar"*}"
		LogMsg "ovs source on ${1} $ovsSrcDir"
		ssh "${1}" "mv ${ovsSrcDir} ${OVS_DIR}"
	elif [[ $ovsSrcLink =~ ".git" ]] || [[ $ovsSrcLink =~ "git:" ]];
	then
		ovsSrcDir="${ovsSrcLink##*/}"
		LogMsg "Installing OVS from source file $ovsSrcDir"
		ssh "${1}" git clone "$ovsSrcLink"
		check_exit_status "git clone $ovsSrcLink on ${1}" "exit"
		LogMsg "ovs source on ${1} $ovsSrcLink"
	else
		LogMsg "Provide proper link $ovsSrcLink"
	fi

	ssh "${1}" "cd ${OVS_DIR} && ./boot.sh"

	LogMsg "Starting OVS configure on ${1}"
	ssh "${1}" "cd ${OVS_DIR} && ./configure --with-dpdk=${RTE_SDK}/${RTE_TARGET} --prefix=/usr --localstatedir=/var --sysconfdir=/etc"

	LogMsg "Starting OVS build on ${1}"
	ssh "${1}" "cd ${OVS_DIR} && make -j16 && make install"
	check_exit_status "ovs build on ${1}" "exit"

	vf_ip=$(ssh "${1}" "ip a | grep ${nicName} -A 2| grep inet | grep ${nicName} | awk '{print \$2}'")

	ssh "${1}" "ip addr flush dev ${nicName}"
	check_exit_status "${nicName} flush on ${1}" "exit"

	ssh "${1}" "/usr/share/openvswitch/scripts/ovs-ctl start"
	check_exit_status "ovs start on ${1}" "exit"

	ssh "${1}" "ovs-vsctl --no-wait set Open_vSwitch . other_config:dpdk-init=true"
	ssh "${1}" "ovs-vsctl --no-wait set Open_vSwitch . other_config:dpdk-lcore-mask=0xFF"
	ssh "${1}" "ovs-vsctl --no-wait set Open_vSwitch . other_config:pmd-cpu-mask=0xFF"

	OVS_BRIDGE="br-dpdk"
	ssh "${1}" "ovs-vsctl add-br "${OVS_BRIDGE}" -- set bridge "${OVS_BRIDGE}" datapath_type=netdev"
	check_exit_status "ovs bridge ${OVS_BRIDGE} create on ${1}" "exit"

	ssh "${1}" "ovs-vsctl add-port "${OVS_BRIDGE}" p1 -- set Interface p1 type=dpdk options:dpdk-devargs=net_tap_vsc0,iface=${nicName}"
	check_exit_status "ovs port added to bridge ${OVS_BRIDGE} on ${1}" "exit"

	ssh "${1}" "ifconfig ${OVS_BRIDGE} ${vf_ip} up"
	check_exit_status "set IP ${vf_ip} for ${OVS_BRIDGE} on ${1}" "exit"

	LogMsg "*********INFO: Installed OVS version on ${1} is ${ovsVersion} ********"
}


# Script start from here

LogMsg "*********INFO: Script execution Started********"
echo "server-vm : eth0 : ${server}"
echo "client-vm : eth0 : ${client}"

LogMsg "*********INFO: Starting setup & configuration of OVS*********"
LogMsg "INFO: Installing OVS on client ${client}..."
install_ovs "${client}"

if [[ ${client} == ${server} ]];
then
	LogMsg "Skip OVS setup on server"
	SetTestStateCompleted
else
	LogMsg "INFO: Installing OVS on server ${server}..."
	install_ovs "${server}"
	SetTestStateCompleted
fi
LogMsg "*********INFO: OVS setup completed*********"
