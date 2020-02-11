#!/bin/bash
#
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
# This script will set up hibernation configuration in the VM.
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

# Load the global variables
source ~/constants.sh

function Main() {
	LogMsg "Starting Hibernation required packages and kernel build in the VM"
	update_repos

	# Install common packages
	req_pkg="gcc make flex bison git build-essential fakeroot libncurses5-dev libssl-dev ccache"
	install_package $req_pkg
	LogMsg "$?: Installed the common required packages; $req_pkg"

	source /etc/os-release

	case $DISTRO in
		redhat_7|centos_7|redhat_8|centos_8)
			;;
		suse*|sles*)
			req_pkg="ncurses-devel libelf-dev"
			install_package $req_pkg
			LogMsg "$?: Installed required packages, $req_pkg"
			;;
		ubuntu*)
			;;
		*)
			LogErr "$DISTRO does not support hibernation"
			SetTestStateFailed
			exit 0
			;;
	esac

	# Prepare swap space
	for key in n p 1 2048 '' t 82 p w
	do
		echo $key >> ~/keys.txt
	done
	LogMsg "Generated the keys.txt file for fdisk commanding"

	sudo cat ~/keys.txt | sudo fdisk /dev/sdc
	LogMsg "$?: Executed fdisk command"

	sudo mkswap /dev/sdc1
	LogMsg "Made the swap space"

	sudo swapon /dev/sdc1
	LogMsg "Enabled the swap space"

	sw_uuid=$(blkid | grep -i sw | awk '{print $2}' | tr -d " " | sed 's/"//g')
	LogMsg "Found the Swap space disk UUID: $sw_uuid"

	sudo chmod 766 /etc/fstab

	sudo echo $sw_uuid none swap sw 0 0 >> /etc/fstab
	LogMsg "Updated /etc/fstab file with swap uuid information"

	# Start kernel compilation
	LogMsg "Clone and compile new kernel from $hb_url"
	git clone $hb_url
	LogMsg "$?: Cloned the kernel source repo"

	cd linux

	git checkout $hb_branch
	LogMsg "$?: Changed to $hb_branch"

	cp /boot/config*-azure ./.config
	LogMsg "$?: Copied the default config file from /boot"

	yes '' | make oldconfig
	LogMsg "$?: Did oldconfig make file"

	make -j $(getconf _NPROCESSORS_ONLN)
	LogMsg "$?: Compiled the source codes"

	make modules_install
	LogMsg "$?: Installed new kernel modules"

	make install
	LogMsg "$?: Install new kernel"

	sed -i -e "s/rootdelay=300/rootdelay=300 resume=$sw_uuid/g" /etc/default/grub.d/50-cloudimg-settings.cfg
	LogMsg "$?: Updated the 50-cloudimg-settings.cfg with resume=$sw_uuid"

	sed -i -e "s/GRUB_HIDDEN_TIMEOUT=*.*/GRUB_HIDDEN_TIMEOUT=30/g" /etc/default/grub.d/50-cloudimg-settings.cfg
	LogMsg "$?: Updated GRUB_HIDDEN_TIMEOUT value with 30"

	sed -i -e "s/GRUB_TIMEOUT=*.*/GRUB_TIMEOUT=30/g" /etc/default/grub.d/50-cloudimg-settings.cfg
	LogMsg "$?: Updated GRUB_TIMEOUT value with 30"

	update-grub2
	LogMsg "$?: Ran update-grub2"

	cd

	LogMsg "Setting hibernate command to test.sh"
	echo 'echo disk > /sys/power/state' > ~/test.sh
	chmod 766 ~/test.sh

	echo "setup_completed=0" >> ~/constants.sh
	LogMsg "Main function completed"
}

# main body
Main
cp ~/TestExecution.log ~/Setup-TestExecution.log
cp ~/TestExecutionError.log ~/Setup-TestExecutionError.log
SetTestStateCompleted
exit 0