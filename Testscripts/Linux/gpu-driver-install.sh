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
    if [[ "$driver" == "CUDA" ]] && ([[ $DISTRO == *"suse"* ]] || [[ $DISTRO == "redhat_8" ]] || [[ $DISTRO == *"debian"* ]]); then
        LogMsg "$DISTRO not supported. Skip the test."
        SetTestStateSkipped
        exit 0
    fi

    if [[ "$driver" == "GRID" ]] && ([[ $DISTRO == "redhat_8" ]] || [[ $DISTRO == *"debian"* ]]); then
        LogMsg "$DISTRO not supported. Skip the test."
        SetTestStateSkipped
        exit 0
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
        # Temporary fix till driver for ubuntu19 series list under http://developer.download.nvidia.com/compute/cuda/repos/
        if [[ $os_RELEASE =~ 19.* ]]; then
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
