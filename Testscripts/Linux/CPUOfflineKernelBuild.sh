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

	if [[ $repo_url != "" ]]; then
		LogMsg "CPU offline and vmbus interrupt reassignement requires kernel build in the VM until the version 5.7"
		update_repos

		# Install common packages
		req_pkg="gcc make bison git"
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
				req_pkg="build-essential fakeroot libncurses5-dev libssl-dev ccache flex dkms"
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
		LogMsg "Clone and compile new kernel from $repo_url"
		git clone $repo_url linux
		LogMsg "$?: Cloned the kernel source repo"

		cd linux

		git checkout $repo_branch
		LogMsg "$?: Changed to $repo_branch"

		config_file="/boot/config-$(uname -r)"

		cp $config_file $basedir/linux/.config
		LogMsg "$?: Copied the default config file from /boot"

		if [[ $DISTRO == "redhat_8" ]]; then
			# comment out those 2 parameters in RHEL 8.x
			sed -i -e "s/CONFIG_SYSTEM_TRUSTED_KEY*.*/#CONFIG_SYSTEM_TRUSTED_KEY/g" ~/.config
			sed -i -e "s/CONFIG_MODULE_SIG_KEY*.*/#CONFIG_MODULE_SIG_KEY/g" ~/.config
		fi

		yes '' | make oldconfig
		LogMsg "Did make oldconfig file"

		make -j $(getconf _NPROCESSORS_ONLN)
		if [ $? ]; then
			LogMsg "Compiled the source codes"
		else
			LogErr "Failed to compile the source code"
			SetTestStateFailed
			exit 0
		fi

		make modules_install
		if [ $? ]; then
			LogMsg "Installed new kernel modules"
		else
			LogErr "Failed to install kernel modules"
			SetTestStateFailed
			exit 0
		fi

		make install
		if [ $? ]; then
			LogMsg "Install new kernel"
		else
			LogErr "Failed to install new kernel"
			SetTestStateFailed
			exit 0
		fi

		if [[ $DISTRO =~ "ubuntu" ]]; then
			update-grub2
			LogMsg "$?: Ran update-grub2"
		fi

		cp $basedir/TestExecution.log $basedir/Setup-TestExecution.log
		cat ./TestExecution.log >> $basedir/Setup-TestExecution.log
		cp $basedir/TestExecutionError,log $basedir/Setup-TestExecutionError.log
		cat ./TestExecutionError.log >> $basedir/Setup-TestExecutionError.log
	fi

	echo "setup_completed=0" >> $basedir/constants.sh
	LogMsg "Main function of setup completed"
}

# main body
Main
SetTestStateCompleted
exit 0