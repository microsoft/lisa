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
# Due to fdisk and hibernate command later, it needs to be running by root.
HOMEDIR="/root"
# Get distro information
GetDistro

# Load the global variables
source /root/constants.sh

function Verify_File {
	# Verify if the file exists or not.
	# The first parameter is absolute path
	if [ -e $1 ]; then
		LogMsg "File found $1"
	else
		LogErr "File not found $1"
	fi
}

function Found_File {
	# The first parameter is file name, the second parameter is filtering
	target_path=$(find / -name $1 | grep $2)
	if [ -n $target_path ]; then
		LogMsg "Verified $1 binary in $target_path successfully"
	else
		LogErr "Could not verify $1 binary in the system"
	fi
}

function Verify_Result {
	# Return OK string, if the latest result is 0
	if [ $? -eq 0 ]; then
		LogMsg "OK"
	else
		LogErr "FAIL"
	fi
}

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

	cp /boot/config*-azure /root/linux/.config
	cd /root/linux
	yes '' | make oldconfig
	make -j $(getconf _NPROCESSORS_ONLN)
	make modules_install
	make install

	sed -i -e 's/rootdelay=300/rootdelay=300 resume=UUID=$uuid/g' /etc/default/grub.d/50-cloudimg-settings.cfg
	Verify_Result

	update-grud2

	echo 'echo disk > /sys/power/state' > /root/test.sh
	chmod 766 /root/test.sh

	echo "setup_completed=0" >> /root/constants.sh
	LogMsg "Completed SetupRDAM process"
	LogMsg "Main function completed"
}

# main body
Main
cp /root/TestExecution.log /root/Setup-TestExecution.log
cp /root/TestExecutionError.log /root/Setup-TestExecutionError.log
SetTestStateCompleted
exit 0