#!/bin/bash
########################################################################
#
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
########################################################################
########################################################################
#
# Description:
#   This script installs nVidia GPU drivers.
#   nVidia CUDA and GRID drivers are supported.
#   Refer to the below link for supported releases:
#   https://docs.microsoft.com/en-us/azure/virtual-machines/linux/n-series-driver-setup
#
# Steps:
#   1. Install dependencies
#   2. Compile and install GPU drivers based on the driver type.
#       The driver type is injected in the constants.sh file, in this format:
#       driver="CUDA" or driver="GRID"
#
#   Please check the below URL for any new versions of the GRID driver:
#   https://docs.microsoft.com/en-us/azure/virtual-machines/linux/n-series-driver-setup
#
########################################################################
#install_package curl jq
grid_driver="https://download.microsoft.com/download/4/3/9/439aea00-a02d-4875-8712-d1ab46cf6a73/NVIDIA-Linux-x86_64-510.47.03-grid-azure.run"

#vmSize=`curl -s -H Metadata:true --noproxy "*" "http://169.254.169.254/metadata/instance?api-version=2021-02-01" | jq '.compute.vmSize'  2>/dev/null`
#
#if [[ $vmSize =~ 'A10' ]] 
#then
#	grid_driver="https://download.microsoft.com/download/4/3/9/439aea00-a02d-4875-8712-d1ab46cf6a73/NVIDIA-Linux-x86_64-510.47.03-grid-azure.run"
#else
#	grid_driver="https://go.microsoft.com/fwlink/?linkid=874272"
#fi
echo "grid_driver: $grid_driver"

#######################################################################
function skip_test() {
	if [[ $driver == "CUDA" ]] && ([[ $DISTRO == *"suse"* ]] || [[ $DISTRO == "redhat_8" ]] || [[ $DISTRO == *"debian"* ]] || [[ $DISTRO == "almalinux_8" ]] || [[ $DISTRO == "rockylinux_8" ]]); then
		LogMsg "$DISTRO not supported. Skip the test."
		SetTestStateSkipped
		exit 0
	fi

	# https://docs.microsoft.com/en-us/azure/virtual-machines/linux/n-series-driver-setup
	# Only support Ubuntu 16.04 LTS, 18.04 LTS, RHEL/CentOS 7.0 ~ 7.9, SLES 12 SP2
	# Azure HPC team defines GRID driver support scope.
	if [[ $driver == "GRID" ]]; then
		support_distro="redhat_7 centos_7 ubuntu_x suse_12"
		unsupport_flag=0
		GetDistro
		source /etc/os-release
		if [[ "$support_distro" == *"$DISTRO"* ]]; then
			if [[ $DISTRO == "redhat_7" ]]; then
				# RHEL 7.x > 7.9 should be skipped
				_minor_ver=$(echo $VERSION_ID | cut -d'.' -f 2)
				if [[ $_minor_ver -gt 9 ]]; then
					unsupport_flag=1
				fi
			fi
			if [[ $DISTRO == "centos_7" ]]; then
				# 7.x > 7.9 should be skipped
				_minor_ver=$(cat /etc/centos-release | cut -d ' ' -f 4 | cut -d '.' -f 2)
				if [[ $_minor_ver -gt 9 ]]; then
					unsupport_flag=1
				fi
			fi
			if [[ $DISTRO == "ubuntu_x" ]]; then
				# skip other ubuntu version than 16.04, 18.04, 20.04, 21.04
				if [[ $VERSION_ID != "16.04" && $VERSION_ID != "18.04" && $VERSION_ID != "20.04" && $VERSION_ID != "21.04" ]]; then
					unsupport_flag=1
				fi
			fi
			if [[ $DISTRO == "suse_12" ]]; then
				# skip others except SLES 12 SP2 BYOS and SAP and SLES 15 SP2,
				# However, they use default-kernel and no repo to Azure customer.
				# This test will fail until SUSE enables azure-kernel for GRID driver installation
				if [ $VERSION_ID != "12.2" || $VERSION_ID != "15.2" ];then
					unsupport_flag=1
				fi
			fi
		else
			unsupport_flag=1
		fi
		if [ $unsupport_flag = 1 ]; then
			LogErr "$DISTRO not supported. Skip the test."
			SetTestStateSkipped
			exit 0
		fi
	fi
}

function InstallCUDADrivers() {
	LogMsg "Starting CUDA driver installation"
	case $DISTRO in
	redhat_7|centos_7)
		CUDA_REPO_PKG="cuda-repo-rhel7-${CUDADriverVersion}.x86_64.rpm"
		LogMsg "Using ${CUDA_REPO_PKG}"

		wget http://developer.download.nvidia.com/compute/cuda/repos/rhel7/x86_64/"${CUDA_REPO_PKG}" -O /tmp/"${CUDA_REPO_PKG}"
		if [ $? -ne 0 ]; then
			LogErr "Failed to download ${CUDA_REPO_PKG}"
			SetTestStateAborted
			return 1
		else
			LogMsg "Successfully downloaded the ${CUDA_REPO_PKG} file in /tmp directory"
		fi

		rpm -ivh /tmp/"${CUDA_REPO_PKG}"
		LogMsg "Installed the rpm package, ${CUDA_REPO_PKG}"

		# For RHEL/CentOS, it might be needed to install vulkan-filesystem to install CUDA drivers.
		# Download and Install vulkan-filesystem
		wget http://mirror.centos.org/centos/7/os/x86_64/Packages/vulkan-filesystem-1.1.97.0-1.el7.noarch.rpm -O /tmp/vulkan-filesystem-1.1.97.0-1.el7.noarch.rpm
		if [ $? -ne 0 ]; then
			LogErr "Failed to download vulkan-filesystem rpm"
			SetTestStateAborted
			return 1
		else
			LogMsg "Successfully downloaded the vulkan-filesystem rpm file in /tmp directory"
		fi
		yum -y install /tmp/vulkan-filesystem-1.1.97.0-1.el7.noarch.rpm

		yum --nogpgcheck -y install cuda-drivers > $HOME/install_drivers.log 2>&1
		if [ $? -ne 0 ]; then
			LogErr "Failed to install the cuda-drivers!"
			SetTestStateAborted
			return 1
		else
			LogMsg "Successfully installed cuda-drivers"
		fi
	;;

	ubuntu*)
		GetOSVersion
		# 20.04 version install differs from older versions. Special case the new version. Abort if version doesn't exist yet.
		if [[ $os_RELEASE =~ 21.* ]] || [[ $os_RELEASE =~ 22.* ]]; then
			LogErr "CUDA Driver may not exist for Ubuntu > 21.XX , check https://developer.download.nvidia.com/compute/cuda/repos/ for new versions."
			SetTestStateAborted;
		fi
		if [ $os_RELEASE = 20.04 ]; then
			LogMsg "Proceeding with installation for 20.04"
			wget -O /etc/apt/preferences.d/cuda-repository-pin-600 https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2004/x86_64/cuda-ubuntu2004.pin
			apt-key adv --fetch-keys https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2004/x86_64/7fa2af80.pub
			add-apt-repository "deb http://developer.download.nvidia.com/compute/cuda/repos/ubuntu2004/x86_64/ /"
		else
			if [[ $os_RELEASE =~ 19.* ]]; then
				LogMsg "There is no cuda driver for $os_RELEASE, used the one for 18.10"
				os_RELEASE="18.10"
			fi
			CUDA_REPO_PKG="cuda-repo-ubuntu${os_RELEASE//./}_${CUDADriverVersion}_amd64.deb"
			LogMsg "Using ${CUDA_REPO_PKG}"

			wget http://developer.download.nvidia.com/compute/cuda/repos/ubuntu"${os_RELEASE//./}"/x86_64/"${CUDA_REPO_PKG}" -O /tmp/"${CUDA_REPO_PKG}"
			if [ $? -ne 0 ]; then
				LogErr "Failed to download ${CUDA_REPO_PKG}"
				SetTestStateAborted
				return 1
			else
				LogMsg "Successfully downloaded ${CUDA_REPO_PKG}"
			fi
		fi

		apt-key adv --fetch-keys http://developer.download.nvidia.com/compute/cuda/repos/ubuntu"${os_RELEASE//./}"/x86_64/7fa2af80.pub
		if [ $os_RELEASE != 20.04 ]; then
			dpkg -i /tmp/"${CUDA_REPO_PKG}"
			LogMsg "Installed ${CUDA_REPO_PKG}"
			dpkg_configure
		fi
		apt update

		apt -y --allow-unauthenticated install cuda-drivers > $HOME/install_drivers.log 2>&1
		if [ $? -ne 0 ]; then
			LogErr "Failed to install cuda-drivers package!"
			SetTestStateAborted
			return 1
		else
			LogMsg "Successfully installed cuda-drivers package"
		fi
	;;
	esac

	find /var/lib/dkms/nvidia* -name make.log -exec cp {} $HOME/nvidia_dkms_make.log \;
	if [[ ! -f "$HOME/nvidia_dkms_make.log" ]]; then
		echo "File not found, make.log" > $HOME/nvidia_dkms_make.log
	fi
}

function InstallGRIDdrivers() {
	LogMsg "Starting GRID driver installation"
	wget "$grid_driver" -O /tmp/NVIDIA-Linux-x86_64-grid.run
	if [ $? -ne 0 ]; then
		LogErr "Failed to download the GRID driver!"
		SetTestStateAborted
		return 1
	else
		LogMsg "Successfully downloaded the GRID driver"
	fi

	cat > /etc/modprobe.d/nouveau.conf<< EOF
	blacklist nouveau
	blacklist lbm-nouveau
EOF
	LogMsg "Updated nouveau.conf file with blacklist"

	pushd /tmp
	chmod +x NVIDIA-Linux-x86_64-grid.run
	./NVIDIA-Linux-x86_64-grid.run --no-nouveau-check --silent --no-cc-version-check
	if [ $? -ne 0 ]; then
		LogErr "Failed to install the GRID driver!"
		SetTestStateAborted
		return 1
	else
		LogMsg "Successfully install the GRID driver"
	fi
	popd

	cp /etc/nvidia/gridd.conf.template /etc/nvidia/gridd.conf
	echo 'IgnoreSP=FALSE' >> /etc/nvidia/gridd.conf
	LogMsg "Added IgnoreSP parameter in gridd.conf"
	find /var/log/* -name nvidia-installer.log -exec cp {} $HOME/nvidia-installer.log \;
	if [[ ! -f "$HOME/nvidia-installer.log" ]]; then
		echo "File not found, nvidia-installer.log" > $HOME/nvidia-installer.log
	fi
}

function install_gpu_requirements() {
	install_package "wget lshw gcc make"
	LogMsg "installed wget lshw gcc make"

	case $DISTRO in
		redhat_7|centos_7|redhat_8|almalinux_8|rockylinux_8)
			if [[ $DISTRO == "centos_7" ]]; then
				# for all releases that are moved into vault.centos.org
				# we have to update the repositories first
				yum -y install centos-release
				if [ $? -eq 0 ]; then
					LogMsg "Successfully installed centos-release"
				else
					LogErr "Failed to install centos-release"
					SetTestStateAborted
					return 1
				fi
				yum clean all
				yum -y install --enablerepo=C*-base --enablerepo=C*-updates kernel-devel-"$(uname -r)" kernel-headers-"$(uname -r)"
				if [ $? -eq 0 ]; then
					LogMsg "Successfully installed kernel-devel package with its header"
				else
					LogErr "Failed to install kernel-devel package with its header"
					SetTestStateAborted
					return 1
				fi
			else
				yum -y install kernel-devel-"$(uname -r)" kernel-headers-"$(uname -r)"
				if [ $? -eq 0 ]; then
					LogMsg "Successfully installed kernel-devel package with its header"
				else
					LogErr "Failed to installed kernel-devel package with its header"
					SetTestStateAborted
					return 1
				fi
			fi

			# Kernel devel package is mandatory for nvdia cuda driver installation.
			# Failure to install kernel devel should be treated as test aborted not failed.
			rpm -q --quiet kernel-devel-$(uname -r)
			if [ $? -ne 0 ]; then
				LogErr "Failed to install the RH/CentOS kernel-devel package"
				SetTestStateAborted
				return 1
			else
				LogMsg "Successfully rpm-ed kernel-devel packages"
			fi

			# mesa-libEGL install/update is require to avoid a conflict between
			# libraries - bugzilla.redhat 1584740
			yum -y install mesa-libGL mesa-libEGL libglvnd-devel
			if [ $? -eq 0 ]; then
				LogMsg "Successfully installed mesa-libGL mesa-libEGL libglvnd-devel"
			else
				LogErr "Failed to install mesa-libGL mesa-libEGL libglvnd-devel"
				SetTestStateAborted
				return 1
			fi

			install_epel
			yum --nogpgcheck -y install dkms
			if [ $? -eq 0 ]; then
				LogMsg "Successfully installed dkms"
			else
				LogErr "Failed to install dkms"
				SetTestStateAborted
				return 1
			fi
		;;

		ubuntu*)
			apt -y install build-essential libelf-dev linux-tools-"$(uname -r)" linux-cloud-tools-"$(uname -r)" python libglvnd-dev ubuntu-desktop
			if [ $? -eq 0 ]; then
				LogMsg "Successfully installed build-essential libelf-dev linux-tools linux-cloud-tools python libglvnd-dev ubuntu-desktop"
			else
				LogErr "Failed to install build-essential libelf-dev linux-tools linux-cloud-tools python libglvnd-dev ubuntu-desktop"
				SetTestStateAborted
				return 1
			fi
		;;

		suse_15*)
			kernel=$(uname -r)
			if [[ "${kernel}" == *azure ]]; then
				zypper install --oldpackage -y kernel-azure-devel="${kernel::-6}"
				if [ $? -eq 0 ]; then
					LogMsg "Successfully installed kernel-azure-devel"
				else
					LogErr "Failed to install kernel-azure-devel"
					SetTestStateAborted
					return 1
				fi
				zypper install -y kernel-devel-azure xorg-x11-driver-video libglvnd-devel
				if [ $? -eq 0 ]; then
					LogMsg "Successfully installed kernel-azure-devel xorg-x11-driver-video libglvnd-devel"
				else
					LogErr "Failed to install kernel-azure-devel xorg-x11-driver-video libglvnd-devel"
					SetTestStateAborted
					return 1
				fi
			else
				zypper install -y kernel-default-devel xorg-x11-driver-video libglvnd-devel
				if [ $? -eq 0 ]; then
					LogMsg "Successfully installed kernel-default-devel xorg-x11-driver-video libglvnd-devel"
				else
					LogErr "Failed to install kernel-default-devel xorg-x11-driver-video libglvnd-devel"
					SetTestStateAborted
					return 1
				fi
			fi
		;;
	esac
}

#######################################################################
#
# Main script body
#
#######################################################################
# Source utils.sh
. utils.sh || {
	echo "ERROR: unable to source utils.sh!"
	echo "TestAborted" > state.txt
	exit 0
}
UtilsInit

GetDistro

# Validate repo availability
update_repos
if [ $? != 0 ]; then
	SetTestStateAborted
fi

# Validate the distro version eligibility
skip_test
_state=$(cat state.txt)
if [ $_state == "TestAborted" ]; then
	LogErr "Stop test procedure here for state, $_state"
	exit 0
fi

# Install dependencies
install_gpu_requirements

if [ "$driver" == "CUDA" ]; then
	InstallCUDADrivers
elif [ "$driver" == "GRID" ]; then
	InstallGRIDdrivers
else
	LogMsg "Driver type not detected, defaulting to CUDA driver."
	InstallCUDADrivers
fi

if [ $? -ne 0 ]; then
	LogErr "Could not install the $driver drivers!"
	SetTestStateFailed
	exit 0
fi

# Check and install lsvmbus
check_lsvmbus
SetTestStateCompleted
exit 0
