#!/bin/bash

#######################################################################
#
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
#######################################################################

#######################################################################
#
#
#
# Description:
#######################################################################

UTIL_FILE="./utils.sh"
. ${UTIL_FILE} || {
    errMsg="Error: missing ${UTIL_FILE} file"
    echo "${errMsg}"
    SetTestStateAborted
    exit 10
}

while echo $1 | grep ^- > /dev/null; do
    eval $( echo $1 | sed 's/-//g' | tr -d '\012')=$2
    shift
    shift
done

if [ -z "$CustomKernel" ]; then
    echo "Please mention -CustomKernel next"
    exit 1
fi
if [ -z "$logFolder" ]; then
    logFolder="~"
    echo "-logFolder is not mentioned. Using ~"
else
    echo "Using Log Folder $logFolder"
fi

#
# Constants/Globals
#
LOCAL_FILE_PREFIX="localfile:"
LOG_FILE="$logFolder/build-CustomKernel.txt"

touch $LOG_FILE

LogMsg()
{
    echo $(date "+%b %d %Y %T") : "${1}"    # Add the time stamp to the log message
    echo "${1}" >> $LOG_FILE
}

CheckInstallLockUbuntu()
{
    pidof dpkg
    if [ $? -eq 0 ];then
        LogMsg "Another install is in progress. Waiting 10 seconds."
        sleep 10
        CheckInstallLockUbuntu
    else
        LogMsg "No lock on dpkg present."
    fi
}

function Install_Build_Deps {
    #
    # Installing packages required for the build process.
    #
    GetDistro
    update_repos
    case "$DISTRO" in
    redhat_7|centos_7)
        install_epel
        LogMsg "Installing package Development Tools"
        yum -y groupinstall "Development Tools"  >> $LOG_FILE 2>&1
        check_exit_status "Install Development Tools" "exit"
        LogMsg "Installing package elfutils-libelf-devel openssl-devel ccache"
        yum_install "elfutils-libelf-devel openssl-devel ccache"  >> $LOG_FILE 2>&1

        # Use ccache to speed up recompilation
        PATH="/usr/lib64/ccache:"$PATH
        ;;

    ubuntu*|debian*)
        CheckInstallLockUbuntu
        LogMsg "Installing package git build-essential bison flex libelf-dev libncurses5-dev xz-utils libssl-dev bc ccache"
        apt_get_install "git build-essential bison flex libelf-dev libncurses5-dev xz-utils libssl-dev bc ccache"  >> $LOG_FILE 2>&1

        PATH="/usr/lib/ccache:"$PATH
        ;;

     *)
        LogMsg "Unsupported distro: $DISTRO"
        SetTestStateAborted
        ;;
    esac
}

function Get_Upstream_Source (){
    #
    # Downloading kernel sources from git
    #
    base_dir="$1"
    source_path="$2"

    git_folder_git_extension=${source_path##*/}
    git_folder=${git_folder_git_extension%%.*}
    source="${base_dir}/${git_folder}"

    pushd "${base_dir}" > /dev/null
    if [[ ! -d "${source}" ]];then
        git clone "$source_path" >> $LOG_FILE 2>&1
    fi
    pushd "$source" > /dev/null
    git reset --hard HEAD~1 > /dev/null
    git fetch > /dev/null
    git checkout -f master > /dev/null

    if [[ $? -ne 0 ]];then
        exit 1
    fi
    git pull > /dev/null
    popd > /dev/null
    popd > /dev/null
    echo "$source"
}

function Build_Kernel (){
    #
    # Building the kernel
    #
    source="$1"
    thread_number=$(grep -c ^processor /proc/cpuinfo)

    pushd "$source"
    LogMsg "Start to make old config"
    make olddefconfig >> $LOG_FILE 2>&1
    check_exit_status "Make kernel config" "exit"

    LogMsg "Start to build kernel"
    make -j$thread_number >> $LOG_FILE 2>&1
    check_exit_status "Build kernel" "exit"

    LogMsg "Start to install modules"
    make modules_install -j$thread_number >> $LOG_FILE 2>&1
    check_exit_status "Install modules" "exit"

    LogMsg "Start to install kernel"
    make install -j$thread_number >> $LOG_FILE 2>&1
    check_exit_status "Install kernel" "exit"

    if [[ $DISTRO -eq redhat_7 ]] || [[ $DISTRO -eq centos_7 ]]; then
        LogMsg "Set GRUB_DEFAULT=0 in /etc/default/grub"
        sed -i 's/GRUB_DEFAULT=saved/GRUB_DEFAULT=0/g' /etc/default/grub
        grub2-mkconfig -o /boot/grub2/grub.cfg >> $LOG_FILE 2>&1
    fi

    popd
}

InstallKernel()
{
    if [ "${CustomKernel}" == "linuxnext" ]; then
        kernelSource="https://git.kernel.org/pub/scm/linux/kernel/git/next/linux-next.git"
    elif [ "${CustomKernel}" == "proposed" ]; then
        export DEBIAN_FRONTEND=noninteractive
        release=$(lsb_release -c -s)
        LogMsg "Enabling proposed repository for $release distro"
        echo "deb http://archive.ubuntu.com/ubuntu/ ${release}-proposed restricted main multiverse universe" >> /etc/apt/sources.list
        rm -rf /etc/apt/preferences.d/proposed-updates
        LogMsg "Installing linux-image-generic from $release proposed repository."
        apt clean all
        apt -y update >> $LOG_FILE 2>&1
        apt -y --fix-missing upgrade >> $LOG_FILE 2>&1
        apt install -y -qq linux-tools-generic/$release-proposed
        apt install -y -qq linux-cloud-tools-generic/$release-proposed
        apt install -y -qq linux-cloud-tools-common/$release-proposed
        kernelInstallStatus=$?
        if [ $kernelInstallStatus -ne 0 ]; then
            LogMsg "CUSTOM_KERNEL_FAIL"
            SetTestStateFailed
        else
            LogMsg "CUSTOM_KERNEL_SUCCESS"
            SetTestStateCompleted
        fi
    elif [ "${CustomKernel}" == "proposed-azure" ]; then
        export DEBIAN_FRONTEND=noninteractive
        release=$(lsb_release -c -s)
        LogMsg "Enabling proposed repository for $release distro"
        echo "deb http://archive.ubuntu.com/ubuntu/ ${release}-proposed restricted main multiverse universe" >> /etc/apt/sources.list
        rm -rf /etc/apt/preferences.d/proposed-updates
        LogMsg "Installing linux-azure kernel from $release proposed repository."
        apt clean all
        apt -y update >> $LOG_FILE 2>&1
        apt install -yq linux-azure/$release >> $LOG_FILE 2>&1
        kernelInstallStatus=$?
        if [ $kernelInstallStatus -ne 0 ]; then
            LogMsg "CUSTOM_KERNEL_FAIL"
            SetTestStateFailed
        else
            LogMsg "CUSTOM_KERNEL_SUCCESS"
            SetTestStateCompleted
        fi
    elif [ "${CustomKernel}" == "proposed-edge" ]; then
        export DEBIAN_FRONTEND=noninteractive
        release=$(lsb_release -c -s)
        LogMsg "Enabling proposed repository for $release distro"
        echo "deb http://archive.ubuntu.com/ubuntu/ ${release}-proposed restricted main multiverse universe" >> /etc/apt/sources.list
        rm -rf /etc/apt/preferences.d/proposed-updates
        LogMsg "Installing linux-azure-edge kernel from $release proposed repository."
        apt clean all
        apt -y update >> $LOG_FILE 2>&1
        apt install -yq linux-azure-edge/$release >> $LOG_FILE 2>&1
        kernelInstallStatus=$?
        if [ $kernelInstallStatus -ne 0 ]; then
            LogMsg "CUSTOM_KERNEL_FAIL"
            SetTestStateFailed
        else
            LogMsg "CUSTOM_KERNEL_SUCCESS"
            SetTestStateCompleted
        fi
    elif [ "${CustomKernel}" == "ppa" ]; then
        DISTRO=$(grep -ihs "buntu\|Suse\|Fedora\|Debian\|CentOS\|Red Hat Enterprise Linux" /etc/{issue,*release,*version})
        if [[ $DISTRO =~ "Ubuntu" ]];
        then
            LogMsg "Enabling ppa repositry..."
            DEBIAN_FRONTEND=noninteractive add-apt-repository --yes ppa:canonical-kernel-team/ppa
            apt -y update >> $LOG_FILE 2>&1
            LogMsg "Installing linux-image-generic from proposed repository."
            apt -y --fix-missing upgrade >> $LOG_FILE 2>&1
            kernelInstallStatus=$?
        fi
        SetTestStateCompleted
        if [ $kernelInstallStatus -ne 0 ]; then
            LogMsg "CUSTOM_KERNEL_FAIL"
            SetTestStateFailed
        else
            LogMsg "CUSTOM_KERNEL_SUCCESS"
            SetTestStateCompleted
        fi
    elif [ "${CustomKernel}" == "latest" ]; then
        DISTRO=$(grep -ihs "buntu\|Suse\|Fedora\|Debian\|CentOS\|Red Hat Enterprise Linux" /etc/{issue,*release,*version})
        if [[ $DISTRO =~ "Ubuntu" ]];
        then
            export DEBIAN_FRONTEND=noninteractive
            LogMsg "Installing linux-image-generic from repository."
            apt -y update >> $LOG_FILE 2>&1
            apt -y --fix-missing upgrade >> $LOG_FILE 2>&1
            LogMsg "Installing linux-image-generic from proposed repository."
            apt -y update >> $LOG_FILE 2>&1
            apt -y --fix-missing upgrade >> $LOG_FILE 2>&1
            kernelInstallStatus=$?
        fi
        SetTestStateCompleted
        if [ $kernelInstallStatus -ne 0 ]; then
            LogMsg "CUSTOM_KERNEL_FAIL"
            SetTestStateFailed
        else
            LogMsg "CUSTOM_KERNEL_SUCCESS"
            SetTestStateCompleted
        fi
    elif [ "${CustomKernel}" == "netnext" ]; then
        kernelSource="https://git.kernel.org/pub/scm/linux/kernel/git/davem/net-next.git"
    elif [[ $CustomKernel == *.deb ]]; then
        LogMsg "Custom Kernel:$CustomKernel"
        apt-get update

        LogMsg "Adding packages required by the kernel."
        apt-get install -y binutils

        LogMsg "Removing packages that do not allow the kernel to be installed"
        apt-get remove -y grub-legacy-ec2

        if [[ $CustomKernel =~ "http" ]];then
            CheckInstallLockUbuntu
            LogMsg "Debian package web link detected. Downloading $CustomKernel"
            apt-get install -y wget
            apt-get remove -y linux-cloud-tools-common
            wget $CustomKernel
            LogMsg "Installing ${CustomKernel##*/}"
            dpkg -i "${CustomKernel##*/}"  >> $LOG_FILE 2>&1
            image_file=$(ls -1 *.deb* | grep -v "dbg" | sed -n 1p)
        else
            CheckInstallLockUbuntu
            customKernelFilesUnExpanded="${CustomKernel#$LOCAL_FILE_PREFIX}"
            if [[ "${customKernelFilesUnExpanded}" == *'*.deb'* ]]; then
                apt-get remove -y linux-cloud-tools-common
            fi

            LogMsg "Installing ${customKernelFilesUnExpanded}"
            eval "dpkg -i $customKernelFilesUnExpanded >> $LOG_FILE 2>&1"
            image_file=$(ls -1 *image* | grep -v "dbg" | sed -n 1p)
        fi

        LogMsg "Configuring the correct kernel boot order"

        if [[ "${image_file}" != '' ]]; then
            kernel_identifier=$(dpkg-deb --info "${image_file}" | grep 'Package: ' | grep -o "image.*")
            kernel_identifier=${kernel_identifier#image-}
            sed -i.bak 's/GRUB_DEFAULT=.*/GRUB_DEFAULT="Advanced options for Ubuntu>Ubuntu, with Linux '$kernel_identifier'"/g' /etc/default/grub
            update-grub
        else
            msg="Kernel correct boot order could not be set."
            LogErr "$msg"
        fi
        kernelInstallStatus=$?

        SetTestStateCompleted
        if [ $kernelInstallStatus -ne 0 ]; then
            LogMsg "CUSTOM_KERNEL_FAIL"
            SetTestStateFailed
        else
            LogMsg "CUSTOM_KERNEL_SUCCESS"
            DEBIAN_FRONTEND=noninteractive apt-get -y remove linux-image-$(uname -r)
            SetTestStateCompleted
        fi
    elif [[ $CustomKernel == *.rpm ]]; then
        LogMsg "Custom Kernel:$CustomKernel"

        if [[ $CustomKernel =~ "http" ]];then
            yum -y install wget
            LogMsg "RPM package web link detected. Downloading $CustomKernel"
            wget $CustomKernel
            LogMsg "Installing ${CustomKernel##*/}"
            rpm -ivh "${CustomKernel##*/}"  >> $LOG_FILE 2>&1
            kernelInstallStatus=$?
        else
            customKernelFilesUnExpanded="${CustomKernel#$LOCAL_FILE_PREFIX}"

            LogMsg "Removing packages that do not allow the kernel to be installed"
            if [[ "${customKernelFilesUnExpanded}" == *'*.rpm'* ]]; then
                yum remove -y hypervvssd hypervkvpd hypervfcopyd hyperv-daemons hyperv-tools
            fi

            LogMsg "Installing ${customKernelFilesUnExpanded}"
            eval "yum -y install $customKernelFilesUnExpanded >> $LOG_FILE 2>&1"
            kernelInstallStatus=$?
        fi
        LogMsg "Configuring the correct kernel boot order"
        sed -i 's%GRUB_DEFAULT=.*%GRUB_DEFAULT=0%' /etc/default/grub
        grub2-mkconfig -o /boot/grub2/grub.cfg

        SetTestStateCompleted
        if [ $kernelInstallStatus -ne 0 ]; then
            LogMsg "CUSTOM_KERNEL_FAIL"
            SetTestStateFailed
        else
            LogMsg "CUSTOM_KERNEL_SUCCESS"
            SetTestStateCompleted
            rpm -e kernel-$(uname -r)
            grub2-set-default 0
        fi
    fi
    if [[ ${CustomKernel} == "linuxnext" ]] || [[ ${CustomKernel} == "netnext" ]]; then
        LogMsg "Custom Kernel:$CustomKernel"
        Install_Build_Deps
        sourceDir=$(Get_Upstream_Source "." "$kernelSource")
        Build_Kernel "$sourceDir"
        if [ $? -eq 0 ]; then
            LogMsg "CUSTOM_KERNEL_SUCCESS"
            SetTestStateCompleted
        else
            LogMsg "CUSTOM_KERNEL_FAIL"
            SetTestStateFailed
        fi
    fi
    SetTestStateCompleted
    return $kernelInstallStatus
}
InstallKernel
exit 0
