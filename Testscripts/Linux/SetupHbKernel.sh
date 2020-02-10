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
source ./constants.sh

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

	# Prepare swap space
	for key in n p 1 2048 2147483647 t 82 w
	do
		echo $key >> ./keys.txt
	done

	sudo cat ./keys.txt | sudo fdisk /dev/sdc

	sudo mkswap /dev/sdc1

	sudo swapon /dev/sdc1

	sw_uuid=$(blkid | grep -i sw | awk '{print $2}' | tr -d " " | sed 's/"//g')

	sudo chmod 766 /etc/fstab

	sudo echo $sw_uuid none swap sw 0 0 >> /etc/fstab

	# Start kernel compilation
	git clone $hb_url
	LogMsg "$?: Cloned the kernel source repo"

	cp /boot/config*-azure ./linux/.config
	LogMsg "$?: Copied the default config file from /boot"

	cd ./linux
	git branch $hb_branch
	LogMsg "$?: Changed to $hb_branch"

	yes '' | make oldconfig
	LogMsg "$?: Did oldconfig make file"

	make -j $(getconf _NPROCESSORS_ONLN)
	LogMsg "$?: Compiled the source codes"

	make modules_install
	LogMsg "$?: Installed new kernel modules"

	make install
	LogMsg "$?: Install new kernel"

	sed -i -e 's/rootdelay=300/rootdelay=300 resume=UUID=$sw_uuid/g' /etc/default/grub.d/50-cloudimg-settings.cfg
	LogMsg "$?: Updated the 50-cloudimg-settings.cfg with resume=UUID=$sw_uuid"

	update-grub2
	LogMsg "$?: Ran update-grub2"

	LogMsg "Setting hibernate command to ./test.sh"
	echo 'echo disk > /sys/power/state' > ./test.sh
	chmod 766 ./test.sh

	echo "setup_completed=0" >> ./constants.sh
	LogMsg "Main function completed"
}

# main body
Main
cp ./TestExecution.log ./Setup-TestExecution.log
cp ./TestExecutionError.log ./Setup-TestExecutionError.log
SetTestStateCompleted
exit 0