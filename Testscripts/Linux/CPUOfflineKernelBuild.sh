#!/bin/bash
#
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
# This script will set up CPU offline feature with vmbus interrupt channel re-assignment.
# This feature will be enabled the kernel version 5.7+
# Select a CPU number where does not associate to vmbus channels; /sys/bus/vmbus/devices/<device ID>/channels/<channel ID>/cpu.
# Set 1 to online file, echo 1 > /sys/devices/system/cpu/cpu<number>/online
# Verify the dmesg log like ‘smpboot: Booting Node xx Processor x APIC 0xXX’
# Set 0 to online file, echo 0 > /sys/devices/system/cpu/cpu<number>/online
# Verify the dmesg log like ‘smpboot: CPU x is now offline’
# Select a CPU number where associates to vmbus channels.
# Set 1 to online file, echo 1 > /sys/devices/system/cpu/cpu<number>/online
# Verify the command error: Device or resource busy
# Set 0 to online file, echo 0 > /sys/devices/system/cpu/cpu<number>/online
# Verify the command error: Device or resource busy
########################################################################################################
# Source utils.sh
. utils.sh || {
	echo "Error: unable to source utils.sh!"
	echo "TestAborted" >state.txt
	exit 0
}
# Source constants file and initialize most common variables
UtilsInit

# Constants/Globals
# Get distro information
GetDistro

function Main() {

	if [[ $repo_url != "" ]]; then
		LogMsg "CPU offline and vmbus interrupt reassignement requires kernel build in the VM until the version 5.7"
		update_repos

		# Install common packages
		req_pkg="gcc make flex bison git"
		install_package $req_pkg
		LogMsg "$?: Installed the required common packages; $req_pkg"

		case $DISTRO in
			redhat_7|centos_7|redhat_8|centos_8)
				req_pkg="elfutils-libelf-devel ncurses-devel bc elfutils-libelf-devel openssl-devel grub2"
				;;
			suse*|sles*)
				req_pkg="ncurses-devel libelf-dev"
				;;
			ubuntu*)
				req_pkg="build-essential fakeroot libncurses5-dev libssl-dev ccache"
				;;
			*)
				LogErr "$DISTRO does not support vmbus channel re-assignment per cpu offline"
				SetTestStateSkipped
				exit 0
				;;
		esac
		install_package $req_pkg
		LogMsg "$?: Installed required packages, $req_pkg"

		# Start kernel compilation
		LogMsg "Clone and compile new kernel from $repo_url to /usr/src/linux"
		git clone $repo_url /usr/src/linux
		LogMsg "$?: Cloned the kernel source repo in /usr/src/linux"

		cd /usr/src/linux/

		git checkout $repo_branch
		LogMsg "$?: Changed to $repo_branch"

		cp /boot/config*-azure /usr/src/linux/.config
		LogMsg "$?: Copied the default config file from /boot"

		yes '' | make oldconfig
		LogMsg "$?: Did oldconfig make file"

		make -j $(getconf _NPROCESSORS_ONLN)
		LogMsg "$?: Compiled the source codes"

		make modules_install
		LogMsg "$?: Installed new kernel modules"

		make install
		LogMsg "$?: Install new kernel"

		cd

		# Append the test log to the main log files.
		cat /usr/src/linux/TestExecution.log >> ~/TestExecution.log
		cat /usr/src/linux/TestExecutionError.log >> ~/TestExecutionError.log
	fi

	sed -i -e "s/GRUB_HIDDEN_TIMEOUT=*.*/GRUB_HIDDEN_TIMEOUT=30/g" /etc/default/grub.d/50-cloudimg-settings.cfg
	LogMsg "$?: Updated GRUB_HIDDEN_TIMEOUT value with 30"

	sed -i -e "s/GRUB_TIMEOUT=*.*/GRUB_TIMEOUT=30/g" /etc/default/grub.d/50-cloudimg-settings.cfg
	LogMsg "$?: Updated GRUB_TIMEOUT value with 30"

	update-grub2
	LogMsg "$?: Ran update-grub2"

	echo "setup_completed=0" >> ~/constants.sh
	LogMsg "Main function of setup completed"
}

# main body
Main
cp ~/TestExecution.log ~/Setup-TestExecution.log
cp ~/TestExecutionError.log ~/Setup-TestExecutionError.log
SetTestStateCompleted
exit 0