#!/bin/bash
#
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
# This script will execute the CPU channel change along with vmbus interrupt re-assignment
# This feature will be enabled the kernel version 5.7+
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

function Main() {

	basedir=$(pwd)

	# RHEL/CentOS need an extra disk for customized kernel compilation
	if [[ $storage == "yes" ]] || [[ $DISTRO == *"redhat"* ]] || [[ $DISTRO == *"centos"* ]]; then
		# Set up new disk
		for key in n p 1 2048 '' t 1 p w
		do
			echo $key >> keys.txt
		done
		LogMsg "Generated the keys.txt file for fdisk commanding"

		cat keys.txt | fdisk /dev/sdc
		LogMsg "$?: Executed fdisk command"

		partprobe
		LogMsg "$?: Updated the kernel with the change"

		ret=$(ls /dev/sd*)
		LogMsg "$?: Listed out /dev/sd* - $ret"

		mkfs -t ext4 /dev/sdc1
		LogMsg "$?: Wrote a file system to the partition"

		mkdir -p $basedir/data
		chmod 777 $basedir/data
		LogMsg "$?: Created a new directory"

		mount /dev/sdc1 $basedir/data
		LogMsg "$?: Mounted the disk partition to the data directory"

		ext_uuid=$(blkid | grep -i ext4 | awk '{print $2}' | tr -d " " | sed 's/"//g' | tail -n 1)
		LogMsg "$?: Found the disk space UUID: $ext_uuid"
		if [[ -z "$ext_uuid" ]];then
			LogErr "New space disk UUID is empty. Abort the test."
			SetTestStateAborted
			exit 0
		fi

		chmod 766 /etc/fstab

		echo $ext_uuid $basedir/data ext4 defaults,nofail 1 2 >> /etc/fstab
		LogMsg "$?: Updated /etc/fstab file with uuid information"
		ret=$(cat /etc/fstab)
		LogMsg "$ret"
		LogMsg "$?: Displayed the contents in /etc/fstab"
	fi

	if [[ $repo_url != "" ]]; then
		LogMsg "CPU offline and vmbus interrupt reassignement requires kernel build in the VM until the version 5.7"
		update_repos

		# Install common packages
		req_pkg="gcc make bison git flex"
		install_package $req_pkg
		LogMsg "$?: Installed the required common packages; $req_pkg"

		case $DISTRO in
			redhat_7|centos_7|redhat_8|centos_8)
				req_pkg="elfutils-libelf-devel ncurses-devel bc elfutils-libelf-devel openssl-devel grub2"
				;;
			suse*|sles*)
				req_pkg="ncurses-devel libopenssl-devel libelf-devel"
				;;
			ubuntu*)
				req_pkg="build-essential fakeroot libncurses5-dev libssl-dev ccache dkms"
				if [[ "${DISTRO_VERSION}" == "16.04" ]]; then
					req_pkg="${req_pkg} bc libelf-dev"
				fi
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
		# RHEL & CentOS need extra space for kernel repo due to different disk partitioning.
		LogMsg "Clone and compile new kernel from $repo_url"
		if [[ $DISTRO == *"redhat"* ]] || [[ $DISTRO == *"centos"* ]]; then
			git clone $repo_url data/linux
			cd data/linux
		else
			git clone $repo_url linux
			cd linux
		fi
		LogMsg "$?: Cloned the kernel source repo"

		git checkout $repo_branch
		LogMsg "$?: Changed to $repo_branch"

		config_file="/boot/config-$(uname -r)"

		if [[ $DISTRO == *"redhat"* ]] || [[ $DISTRO == *"centos"* ]]; then
			cp $config_file $basedir/data/linux/.config
		else
			cp $config_file $basedir/linux/.config
		fi
		LogMsg "$?: Copied the default config file from /boot"

		if [[ $DISTRO == "redhat_8" ]]; then
			# comment out those 2 parameters in RHEL 8.x
			sed -i -e "s/CONFIG_SYSTEM_TRUSTED_KEY*.*/#CONFIG_SYSTEM_TRUSTED_KEY/g" .config
			sed -i -e "s/CONFIG_MODULE_SIG_KEY*.*/#CONFIG_MODULE_SIG_KEY/g" .config
		fi

		if [[ $DISTRO == *"redhat"* ]] || [[ $DISTRO == *"centos"* ]]; then
			yes '' | make prepare
			LogMsg "Did make prepare"
		else
			yes '' | make oldconfig
			LogMsg "Did make oldconfig"
		fi

		make -j $(getconf _NPROCESSORS_ONLN)
		LogMsg "Compiled the source codes"

		make modules_install
		LogMsg "Installed new kernel modules"

		make install
		LogMsg "Install new kernel"

		if [[ $DISTRO =~ "ubuntu" ]]; then
			update-grub2
			LogMsg "$?: Ran update-grub2"
		fi

		if [ -f ./TestExecution.log ]; then
			cp $basedir/TestExecution.log $basedir/Setup-TestExecution.log
			chmod 766 $basedir/Setup-TestExecution.log
			cat ./TestExecution.log >> $basedir/Setup-TestExecution.log
		fi
		if [ -f ./TestExecutionError.log ]; then
			cp $basedir/TestExecutionError.log $basedir/Setup-TestExecutionError.log
			chmod 766 $basedir/Setup-TestExecutionError.log
			cat ./TestExecutionError.log >> $basedir/Setup-TestExecutionError.log
		fi
		cd $basedir
	fi

	echo "setup_completed=0" >> $basedir/constants.sh
	LogMsg "Main function of setup completed"
}

# main body
Main
SetTestStateCompleted
exit 0