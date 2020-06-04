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

grid_driver="https://go.microsoft.com/fwlink/?linkid=874272"

#######################################################################
function skip_test() {
    if [[ $driver == "CUDA" ]] && ([[ $DISTRO == *"suse"* ]] || [[ $DISTRO == "redhat_8" ]] || [[ $DISTRO == *"debian"* ]]); then
        LogMsg "$DISTRO not supported. Skip the test."
        SetTestStateSkipped
        exit 0
    fi

    # https://docs.microsoft.com/en-us/azure/virtual-machines/linux/n-series-driver-setup
    # Only support Ubuntu 16.04 LTS, 18.04 LTS, RHEL/CentOS 7.0 ~ 7.7, SLES 12 SP2
    # Azure HPC team defines GRID driver support scope.
    if [[ $driver == "GRID" ]]; then
        support_distro="redhat_7 centos_7 ubuntu_x suse_12"
        unsupport_flag=0
        GetDistro
        source /etc/os-release
        if [ "$support_distro" == *"$DISTRO"* ]; then
            if [ ($DISTRO == "redhat_7" || $DISTRO == "centos_8") ]; then
                # RHEL/CentOS 7.8 should be skipped
                if [[ $VERSION_ID > "7.7" ]; then
                    unsupport_flag=1
                fi
                break
            fi
            if [ $DISTRO == "ubuntu_x" ]; then
                # skip other ubuntu version than 16.04 and 18.04
                if [ $VERSION_ID != "16.04" || $VERSION_ID != "18.04" ]; then
                    unsupport_flag=1
                fi
                break
            fi
            if [ $DISTRO == "suse_12" ]; then
                # skip others except SLES 12 SP2
                if [ $VERSION_ID != "12.2" ];then
                    unsupport_flag=1
                fi
            fi
        else
            unsupport_flag=1
        fi
        if [ ! $unsupport_flag ]; then
            LogMsg "$DISTRO not supported. Skip the test."
            SetTestStateSkipped
            exit 0
        fi
    fi
}

function InstallCUDADrivers() {
    LogMsg "Starting CUDA driver installation"
    case $DISTRO in
    redhat_7|centos_7)
        CUDA_REPO_PKG="cuda-repo-rhel7-$CUDADriverVersion.x86_64.rpm"
        LogMsg "Using $CUDA_REPO_PKG"

        wget http://developer.download.nvidia.com/compute/cuda/repos/rhel7/x86_64/"$CUDA_REPO_PKG" -O /tmp/"$CUDA_REPO_PKG"
        if [ $? -ne 0 ]; then
            LogErr "Failed to download $CUDA_REPO_PKG"
            SetTestStateAborted
            return 1
        else
            LogMsg "Successfully downloaded the $CUDA_REPO_PKG file in /tmp directory"
        fi

        rpm -ivh /tmp/"$CUDA_REPO_PKG"
        LogMsg "Installed the rpm package, $CUDA_REPO_PKG"
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
        # Temporary fix till driver for ubuntu19 and ubuntu20 series list under http://developer.download.nvidia.com/compute/cuda/repos/
        if [[ $os_RELEASE =~ 19.* ]] || [[ $os_RELEASE =~ 20.* ]]; then
            LogMsg "There is no cuda driver for $os_RELEASE, used the one for 18.10"
            os_RELEASE="18.10"
        fi
        CUDA_REPO_PKG="cuda-repo-ubuntu${os_RELEASE//./}_${CUDADriverVersion}_amd64.deb"
        LogMsg "Using ${CUDA_REPO_PKG}"

        wget http://developer.download.nvidia.com/compute/cuda/repos/ubuntu"${os_RELEASE//./}"/x86_64/"${CUDA_REPO_PKG}" -O /tmp/"${CUDA_REPO_PKG}"
        if [ $? -ne 0 ]; then
            LogErr "Failed to download $CUDA_REPO_PKG"
            SetTestStateAborted
            return 1
        else
            LogMsg "Successfully downloaded $CUDA_REPO_PKG"
        fi

        apt-key adv --fetch-keys http://developer.download.nvidia.com/compute/cuda/repos/ubuntu"${os_RELEASE//./}"/x86_64/7fa2af80.pub
        dpkg -i /tmp/"$CUDA_REPO_PKG"
        LogMsg "Installed $CUDA_REPO_PKG"
        dpkg_configure
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
		redhat_7|centos_7|redhat_8)
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
update_repos
skip_test
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

if [ -f /usr/libexec/platform-python ]; then
    ln -s /usr/libexec/platform-python /sbin/python
    wget https://raw.githubusercontent.com/torvalds/linux/master/tools/hv/lsvmbus
    chmod +x lsvmbus
    mv lsvmbus /usr/sbin
fi

SetTestStateCompleted
exit 0
