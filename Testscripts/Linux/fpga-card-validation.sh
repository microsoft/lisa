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
#   This script assumes Xilinx XRT tools are available on the VM
#   and tries to run the validation test to make sure FPGA cards
#   are functional. 
#
#
########################################################################

#######################################################################
function check_os(){
    GetOSVersion
    if [[ "$DISTRO" == "ubuntu"* && "$os_RELEASE" != $SupportedUbuntu ]]; then
        LogErr "Ubuntu $os_RELEASE is not supported"
        return 1
    fi
    if [[ "$DISTRO" == "centos_7" && "$os_RELEASE" != $SupportedCentOS ]]; then
        LogErr "CentOS $os_RELEASE is not supported"
        return 1
    fi
}

function check_kernel(){
    if [[ "$DISTRO" == "ubuntu"* ]]; then
        kernel=$(uname -r)
        if ! [[ $kernel  =~ $SupportedUbuntuKernel.* ]]; then
            LogErr "Kernel $kernel is not supported"
            return 1
        fi
    fi
}

function prepare() {
    xrt_setup="/opt/xilinx/xrt/setup.sh"
    if [[ ! -f $xrt_setup ]]; then
        LogErr "$xrt_setup file not found on the VM!"
        return 1
    fi
    source $xrt_setup
}

function get_repo(){
    # do not wait on username/password prompt
    git clone -c core.askPass $echo $XRTRepoUrl /tmp/xrt
    if [ $? -ne 0 ]; then
        LogErr "Unable to clone $XRTRepoUrl"
        return 1
    fi
    cd /tmp/xrt
    git checkout $XRTBranchVersion
    cd /tmp/xrt/src/runtime_src/tools/scripts
    ./xrtdeps.sh
    cd /tmp/xrt/build
}

function install_xrt(){
    LogMsg "Installing XRT ..."
    current_dir=$(pwd)
    case $DISTRO in
        ubuntu*)
            apt-get update
            get_repo
            if [ $? -ne 0 ]; then
                LogErr "Unable to setup the XRT repository"
                return 1
            fi
            ./build.sh clean
            ./build.sh
            cd Release
            apt -y install ./xrt_*-xrt.deb
            apt -y install ./xrt_*-azure.deb
            service mpd restart
            XDMA_PKG="${XDMAFileName}_$SupportedUbuntu.deb"
            wget https://www.xilinx.com/bin/public/openDownload?filename="$XDMA_PKG" -O /tmp/"$XDMA_PKG"
            apt -y install /tmp/"$XDMA_PKG"
            cd ${current_dir}
            prepare
            ;;

        centos_7)
            sudo yum install -y git
            get_repo
            if [ $? -ne 0 ]; then
                LogErr "Unable to setup the XRT repository"
                return 1
            fi
            yum install -y devtoolset-9
            export PATH=/opt/rh/devtoolset-9/root/usr/bin:$PATH
            export LD_LIBRARY_PATH=/opt/rh/devtoolset-9/root/usr/lib64:/opt/rh/devtoolset-9/root/usr/lib:/opt/rh/devtoolset-9/root/usr/lib64/dyninst:/opt/rh/devtoolset-9/root/usr/lib/dyninst:/opt/rh/devtoolset-9/root/usr/lib64:/opt/rh/devtoolset-9/root/usr/lib:$LD_LIBRARY_PATH
            ./build.sh clean
            ./build.sh
            cd Release
            pip install numpy==1.16
            yum install -y ./xrt_*-xrt.rpm
            yum install -y ./xrt_*-azure.rpm
            service mpd restart
            XDMA_PKG="$XDMAFileName.x86_64.rpm"
            wget https://www.xilinx.com/bin/public/openDownload?filename="$XDMA_PKG" -O /tmp/"$XDMA_PKG"
            yum install -y /tmp/"$XMDA_PKG"
            cd ${current_dir}
            prepare
            ;;

        *)
            LogErr "$DISTRO is not supported"
            return 1
    esac
    LogMsg "Finished installing XRT"
}

function validate_cards() {
    LogMsg "Validating FPGA cards ..."
    if ! [ -x "$(command -v xbutil)" ]; then
        LogErr "xbutil not found in the path!"
        SetTestStateAborted
        return 1
    fi
    echo "****************************" >> TestExecution.log
    echo "Running xbutil scan" >> TestExecution.log
    echo "****************************" >> TestExecution.log
    xbutil scan >> TestExecution.log

    echo "****************************" >> TestExecution.log
    echo "Running xbutil validate" >> TestExecution.log
    echo "****************************" >> TestExecution.log
    xbutil validate >> TestExecution.log

    echo "****************************" >> TestExecution.log
    echo "Running xbutil host_mem -d 0 --enable --size 1g" >> TestExecution.log
    echo "****************************" >> TestExecution.log
    xbutil host_mem -d 0 --enable --size 1g >> TestExecution.log

    echo "****************************" >> TestExecution.log
    echo "Running xbutil validate" >> TestExecution.log
    echo "****************************" >> TestExecution.log
    xbutil validate >> TestExecution.log

    echo "****************************" >> TestExecution.log
    echo "Running xbutil reset" >> TestExecution.log
    echo "****************************" >> TestExecution.log
    echo "y"| xbutil reset 1>/dev/null 2>> TestExecution.log

    echo "****************************" >> TestExecution.log
    echo "Running xbutil validate -q" >> TestExecution.log
    echo "****************************" >> TestExecution.log
    xbutil validate -q >> TestExecution.log
}

#######################################################################
#
# Main script body
#
#######################################################################
# Source utils.sh
. utils.sh || {
    echo "ERROR: unable to source utils.sh!"
    SetTestStateAborted
    exit 0
}
UtilsInit
check_os
if [ $? -ne 0 ]; then
    SetTestStateFailed
    exit 0
fi
check_kernel
if [ $? -ne 0 ]; then
    SetTestStateFailed
    exit 0
fi
prepare || install_xrt
if [ $? -ne 0 ]; then
    LogErr "Failed to install XRT"
    SetTestStateFailed
    exit 0
fi
validate_cards

if [ $? -ne 0 ]; then
    LogErr "Could not validate cards!"
    SetTestStateFailed
    exit 0
fi

SetTestStateCompleted
exit 0
