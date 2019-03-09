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
########################################################################

#######################################################################
#
# Install dependencies
#
#######################################################################
function InstallRequirements() {
    case $DISTRO in
    redhat_7|centos_7)
        if [[ $DISTRO -eq centos_7 ]]; then
            # for all releases that are moved into vault.centos.org
            # we have to update the repositories first
            yum -y install centos-release
            yum clean all
            yum -y install --enablerepo=C*-base --enablerepo=C*-updates kernel-devel-"$(uname -r)" kernel-headers-"$(uname -r)"
        else
            yum -y install kernel-devel-"$(uname -r)" kernel-headers-"$(uname -r)"
        fi

        # mesa-libEGL install/update is require to avoid a conflict between
        # libraries - bugzilla.redhat 1584740
        yum -y install mesa-libGL mesa-libEGL libglvnd-devel

        install_epel
        yum --nogpgcheck -y install dkms
    ;;

    ubuntu*)
        apt -y install build-essential libelf-dev linux-tools-"$(uname -r)" linux-cloud-tools-"$(uname -r)"
    ;;
esac
}

function InstallCUDADrivers() {
    case $DISTRO in
    redhat_7|centos_7)
        CUDA_REPO_PKG="cuda-repo-rhel7-${CUDADriverVersion}.x86_64.rpm"
        LogMsg "Using ${CUDA_REPO_PKG}"

        wget http://developer.download.nvidia.com/compute/cuda/repos/rhel7/x86_64/"${CUDA_REPO_PKG}" -O /tmp/"${CUDA_REPO_PKG}"
        if [ $? -ne 0 ]; then
            LogErr "Failed to download ${CUDA_REPO_PKG}"
            SetTestStateAborted
            return 1
        fi

        rpm -ivh /tmp/"${CUDA_REPO_PKG}"
        yum --nogpgcheck -y install cuda-drivers
        if [ $? -ne 0 ]; then
            LogErr "Failed to install the cuda-drivers!"
            SetTestStateAborted
            return 1
        fi
    ;;

    ubuntu*)
        GetOSVersion
        CUDA_REPO_PKG="cuda-repo-ubuntu${os_RELEASE//./}_${CUDADriverVersion}_amd64.deb"
        LogMsg "Using ${CUDA_REPO_PKG}"

        wget http://developer.download.nvidia.com/compute/cuda/repos/ubuntu"${os_RELEASE//./}"/x86_64/"${CUDA_REPO_PKG}" -O /tmp/"${CUDA_REPO_PKG}"
        if [ $? -ne 0 ]; then
            LogErr "Failed to download ${CUDA_REPO_PKG}"
            SetTestStateAborted
            return 1
        fi

        apt-key adv --fetch-keys http://developer.download.nvidia.com/compute/cuda/repos/ubuntu"${os_RELEASE//./}"/x86_64/7fa2af80.pub
        dpkg -i /tmp/"${CUDA_REPO_PKG}"
        dpkg_configure
        apt update

        apt -y --allow-unauthenticated install cuda-drivers
        if [ $? -ne 0 ]; then
            LogErr "Failed to install cuda-drivers package!"
            SetTestStateAborted
            return 1
        fi
    ;;
esac
}

function InstallGRIDdrivers() {
    wget https://go.microsoft.com/fwlink/?linkid=874272 -O /tmp/NVIDIA-Linux-x86_64-grid.run
    if [ $? -ne 0 ]; then
        LogErr "Failed to download the GRID driver!"
        SetTestStateAborted
        return 1
    fi

    cat > /etc/modprobe.d/nouveau.conf<< EOF
    blacklist nouveau
    blacklist lbm-nouveau
EOF

    pushd /tmp
    chmod +x NVIDIA-Linux-x86_64-grid.run
    ./NVIDIA-Linux-x86_64-grid.run --no-nouveau-check --silent --no-cc-version-check
    if [ $? -ne 0 ]; then
        LogErr "Failed to install the GRID driver!"
        SetTestStateAborted
        return 1
    fi
    popd

    cp /etc/nvidia/gridd.conf.template /etc/nvidia/gridd.conf
    echo 'IgnoreSP=FALSE' >> /etc/nvidia/gridd.conf
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
install_package wget lshw gcc

InstallRequirements
check_exit_status "Install requirements" "exit"

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

SetTestStateCompleted
exit 0