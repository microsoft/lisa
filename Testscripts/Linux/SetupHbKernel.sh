#!/bin/bash
#
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
# This script will set up hibernation configuration in the VM.
########################################################################################################
# Source utils.sh
. utils.sh || {
	echo "Error: unable to source utils.sh!"
	echo "TestAborted" > state.txt
	exit 0
}
# Source constants file and initialize most common variables
UtilsInit

# Constants/Globals
# Get distro information
GetDistro

# Get generation: 1/2
GetGuestGeneration

# Hibernation is supported in RHEL-8 since kernel-4.18.0-202. Not supported in RHEL-7.
if [[ $DISTRO =~ "redhat" ]];then
	MIN_KERNEL="4.18.0-202"
	CheckVMFeatureSupportStatus $MIN_KERNEL
	if [[ $? == 1 ]];then
		UpdateSummary "Hibernation is supported since kernel-4.18.0-202. Current version: $(uname -r). Skip the test."
		SetTestStateSkipped
		exit 0
	fi
fi

function Main() {
	# Prepare swap space
	for key in n p 1 2048 '' t 82 p w
	do
		echo $key >> keys.txt
	done
	LogMsg "Generated the keys.txt file for fdisk commanding"

	cat keys.txt | fdisk /dev/sdc
	LogMsg "$?: Executed fdisk command"
	ret=$(ls /dev/sd*)
	LogMsg "$?: List out /dev/sd* - $ret"

	mkswap /dev/sdc1
	LogMsg "$?: Set up the swap space"

	swapon /dev/sdc1
	LogMsg "$?: Enabled the swap space"
	ret=$(swapon -s)
	LogMsg "$?: Show the swap on information - $ret"

	sw_uuid=$(blkid | grep -i sw | awk '{print $2}' | tr -d " " | sed 's/"//g')
	LogMsg "$?: Found the Swap space disk UUID: $sw_uuid"
	if [[ -z "$sw_uuid" ]];then
		LogErr "Swap space disk UUID is empty. Abort the test."
		SetTestStateAborted
		exit 0
	fi

	chmod 766 /etc/fstab

	echo $sw_uuid none swap sw 0 0 >> /etc/fstab
	LogMsg "$?: Updated /etc/fstab file with swap uuid information"
	ret=$(cat /etc/fstab)
	LogMsg "$?: Displayed the contents in /etc/fstab"

	if [[ $hb_url != "" ]]; then
		LogMsg "Starting Hibernation required packages and kernel build in the VM"
		update_repos

		# Install common packages
		req_pkg="gcc make flex bison git"
		install_package $req_pkg
		LogMsg "$?: Installed the common required packages; $req_pkg"

		case $DISTRO in
			redhat_7|centos_7|redhat_8|centos_8)
				req_pkg="elfutils-libelf-devel ncurses-devel bc elfutils-libelf-devel openssl-devel grub2"
				;;
			suse*|sles*)
				req_pkg="ncurses-devel libelf-dev"
				;;
			ubuntu*)
				req_pkg="build-essential fakeroot libncurses5-dev libssl-dev ccache bc"
				;;
			*)
				LogErr "$DISTRO does not support hibernation"
				SetTestStateFailed
				exit 0
				;;
		esac
		install_package $req_pkg
		LogMsg "$?: Installed required packages, $req_pkg"

		# Start kernel compilation
		LogMsg "Clone and compile new kernel from $hb_url to /usr/src/linux"
		git clone $hb_url /usr/src/linux
		LogMsg "$?: Cloned the kernel source repo in /usr/src/linux"

		cd /usr/src/linux/

		git checkout $hb_branch
		LogMsg "$?: Changed to $hb_branch"

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
		if [ -f /usr/src/linux/TestExecution.log ]; then
			cat /usr/src/linux/TestExecution.log >> TestExecution.log
		fi
		if [ -f /usr/src/linux/TestExecutionError.log ]; then
			cat /usr/src/linux/TestExecutionError.log >> TestExecutionError.log
		fi
	fi

	if [[ "$DISTRO" =~ "redhat" ]];then
		_entry=$(cat /etc/default/grub | grep 'rootdelay=')
		if [ $_entry ]; then
			sed -i -e "s/rootdelay=300/rootdelay=300 resume=$sw_uuid/g" /etc/default/grub
			LogMsg "$?: Updated the /etc/default/grub with resume=$sw_uuid"
		else
			echo 'rootdelay=300 resume=$sw_uuid' >> /etc/default/grub
			LogMsg "$?: Added resume=$sw_uuid in /etc/default/grub file"
		fi

		if [[ "$os_GENERATION" == "2" ]];then
			grub_cfg="/boot/efi/EFI/redhat/grub.cfg"
		else
			grub_cfg="/boot/grub2/grub.cfg"
		fi
		grub2-mkconfig -o ${grub_cfg}
		LogMsg "$?: Run grub2-mkconfig -o ${grub_cfg}"

		# Must run dracut -f, or it cannot recover image in boot after hibernation
		dracut -f
		LogMsg "$?: Run dracut -f"
	else
		_entry=$(cat /etc/default/grub.d/50-cloudimg-settings.cfg | grep 'rootdelay=')
		if [ $_entry ]; then
			sed -i -e "s/rootdelay=300/rootdelay=300 resume=$sw_uuid/g" /etc/default/grub.d/50-cloudimg-settings.cfg
			LogMsg "$?: Updated the 50-cloudimg-settings.cfg with resume=$sw_uuid"
		else
			echo 'rootdelay=300 resume=$sw_uuid' >> /etc/default/grub.d/50-cloudimg-settings.cfg
			LogMsg "$?: Added resume=$sw_uuid in 50-cloudimg-settings.cfg file"
		fi

		_entry=$(cat /etc/default/grub.d/50-cloudimg-settings.cfg | grep 'GRUB_HIDDEN_TIMEOUT=')
		if [ $_entry ]; then
			sed -i -e "s/GRUB_HIDDEN_TIMEOUT=*.*/GRUB_HIDDEN_TIMEOUT=30/g" /etc/default/grub.d/50-cloudimg-settings.cfg
			LogMsg "$?: Updated GRUB_HIDDEN_TIMEOUT value with 30"
		else
			echo 'GRUB_HIDDEN_TIMEOUT=30' >> /etc/default/grub.d/50-cloudimg-settings.cfg
			LogMsg "$?: Added GRUB_HIDDEN_TIMEOUT=30 in 50-cloudimg-settings.cfg file"
		fi

		_entry=$(cat /etc/default/grub.d/50-cloudimg-settings.cfg | grep 'GRUB_TIMEOUT=')
		if [ $_entry ]; then
			sed -i -e "s/GRUB_TIMEOUT=*.*/GRUB_TIMEOUT=30/g" /etc/default/grub.d/50-cloudimg-settings.cfg
			LogMsg "$?: Updated GRUB_TIMEOUT value with 30"
		else
			echo 'GRUB_TIMEOUT=30' >> /etc/default/grub.d/50-cloudimg-settings.cfg
			LogMsg "$?: Added GRUB_TIMEOUT=30 in 50-cloudimg-settings.cfg file"
		fi

		update-grub2
		LogMsg "$?: Ran update-grub2"

		_entry1=$(cat /etc/default/grub.d/50-cloudimg-settings.cfg | grep 'rootdelay=')
		_entry2=$(cat /etc/default/grub.d/50-cloudimg-settings.cfg | grep 'GRUB_HIDDEN_TIMEOUT=')
		_entry3=$(cat /etc/default/grub.d/50-cloudimg-settings.cfg | grep 'GRUB_TIMEOUT=')
		if [ $_entry1 && $_entry2 && $_entry3 ]; then
			LogMsg "Successfully update 50-cloudimg-settings.cfg file"
		else
			LogErr "$_entry, $_entry2, $_entry3 - Missing config update in 50-cloudimg-settings.cfg file"
			SetTestStateAborted
			exit 0
		fi
	fi

	echo "setup_completed=0" >> constants.sh
	LogMsg "Main function completed"
}

# main body
Main
cp TestExecution.log Setup-TestExecution.log
cp TestExecutionError.log Setup-TestExecutionError.log
SetTestStateCompleted
exit 0
