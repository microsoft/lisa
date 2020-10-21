#!/bin/bash

#######################################################################
#
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
#######################################################################

#######################################################################
#
# Description:
#  This script is used to deploy Linux kernel.
#  Various installation sources are supported - web, git, rpm/deb packages.
#
#######################################################################

supported_kernels=(ppa proposed proposed-azure proposed-edge latest
                    linuxnext netnext upstream-stable)
tarDestination="./linux-source"
packageDir=$(pwd)
# Source utils.sh
. utils.sh || {
    echo "ERROR: unable to source utils.sh!"
    echo "TestAborted" > state.txt
    exit 0
}
UtilsInit

while echo $1 | grep ^- > /dev/null; do
    eval $( echo $1 | sed 's/-//g' | tr -d '\012')=$2
    shift
    shift
done

# check for either if the custom kernel is a set of rpm/deb packages
# or a support kernel from the above list
if [[ -z "$CustomKernel" ]] || [[ "$CustomKernel" != @(*.rpm|*.deb|*tar.gz|*.tar) ]]; then
    if [[ ! " ${supported_kernels[*]} " =~ $CustomKernel ]]; then
        echo "Please mention a set of rpm/deb kernel packages, or a supported kernel type
        with -CustomKernel, accepted values are: ${supported_kernels[@]}"
        exit 1
    fi
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

function LogMsg() {
    echo $(date "+%b %d %Y %T") : "${1}"    # Add the time stamp to the log message
    echo "${1}" >> $LOG_FILE
}

function Install_Build_Deps {
    #
    # Installing packages required for the build process
    #
    GetDistro
    update_repos
    case "$DISTRO" in
    redhat_7|centos_7|redhat_8|centos_8)
        install_epel
        LogMsg "Installing package Development Tools"
        yum -y groupinstall "Development Tools"  >> $LOG_FILE 2>&1
        check_exit_status "Install Development Tools" "exit"
        LogMsg "Installing package elfutils-libelf-devel openssl-devel ccache"
        yum_install "elfutils-libelf-devel openssl-devel ccache"  >> $LOG_FILE 2>&1

        # Use ccache to speed up recompilation
        PATH="/usr/lib64/ccache:"$PATH

        # git from default CentOS/RedHat 7.x does not support git tag format syntax
        # temporarily use a community repo, then remove it
        if [[ ${CustomKernel} == "upstream-stable" ]]; then
            yum remove -y git
            rpm -U https://centos7.iuscommunity.org/ius-release.rpm
            yum install -y git2u
            rpm -e ius-release
        fi
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

function Get_Upstream_Source() {
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

    # for upstream stable we want to get the latest release,
    # not the master branch which defaults to linux-next daily
    if [[ ${CustomKernel} == "upstream-stable" ]]; then
        # get the most recent release tree, example "v4.19"
        tree_version=$(git tag | sort --version-sort --reverse | grep -E "^v[0-9]{1,3}\.[0-9]{1,3}$" -m1)
        # get the latest version from the tree, example "refs/tags/v4.19.11"
        release=$(git tag -l --format='%(refname)' | grep -E "$tree_version" | sort --version-sort | tail -1)
        git checkout -f "$release" > /dev/null
    else
        git checkout -f master > /dev/null
    fi

    if [[ $? -ne 0 ]];then
        exit 1
    fi

    git pull > /dev/null
    popd > /dev/null
    popd > /dev/null
    echo "$source"
}

function Build_Kernel() {
    #
    # Building the kernel
    #
    source="$1"
    thread_number=$(nproc)

    pushd "$source"
    LogMsg "Start to make old config"
    make olddefconfig >> $LOG_FILE 2>&1
    check_exit_status "Make kernel config" "exit"

    LogMsg "Start to build kernel"
    make -j"$thread_number" >> $LOG_FILE 2>&1
    check_exit_status "Build kernel" "exit"

    LogMsg "Start to install modules"
    make modules_install -j"$thread_number" >> $LOG_FILE 2>&1
    check_exit_status "Install modules" "exit"

    LogMsg "Start to install kernel"
    make install -j"$thread_number" >> $LOG_FILE 2>&1
    check_exit_status "Install kernel" "exit"

    if [[ $DISTRO -eq redhat_7 ]] || [[ $DISTRO -eq centos_7 ]] || \
    [[ $DISTRO -eq redhat_8 ]] || [[ $DISTRO -eq centos_8 ]]; then
        LogMsg "Set GRUB_DEFAULT=0 in /etc/default/grub"
        sed -i 's/GRUB_DEFAULT=saved/GRUB_DEFAULT=0/g' /etc/default/grub
        grub2-mkconfig -o /boot/grub2/grub.cfg >> $LOG_FILE 2>&1
    fi
    popd
}

function Get_Kernel_Name() {
    count=$(find -name "*.deb" -type f | wc -l)
    if [[ $count -gt 1 ]]; then
        CustomKernel="*.deb"
    elif [[ $count -eq 1 ]]; then
        CustomKernel=$(find -name "*.deb" -type f)
    fi
    count=$(find -name "*.rpm" -type f | wc -l)
    if [ $count -gt 1 ]; then
        CustomKernel="*.rpm"
    elif [ $count -eq 1 ]; then
        CustomKernel=$(find -name "*.rpm" -type f)
    fi
    echo "${CustomKernel}"
}

function InstallKernel() {
    if [[ $CustomKernel =~ "http" ]];then
        install_package wget
        IFS=', ' read -r -a array <<<  "$CustomKernel"
        for url in "${array[@]}"; do
            LogMsg "Web link detected. Downloading $url"
            wget "$url"
        done
        if [[ "${#array[@]}" -gt 1 ]]; then
            CustomKernel="$(Get_Kernel_Name)"
        fi
        if [[ "${#array[@]}" -eq 1 ]]; then
            CustomKernel="${CustomKernel##*/}"
        fi
    fi

    if [[ $CustomKernel = *tar.gz || $CustomKernel = *.tar ]]; then
        mkdir -p $tarDestination
        tar -xf "${CustomKernel#$LOCAL_FILE_PREFIX}" -C $tarDestination --strip-components=1
        tarDir=${tarDestination#*/}
        packageDir=${packageDir}/${tarDir}
        CustomKernel="$(Get_Kernel_Name)"
    fi

    if [ "${CustomKernel}" == "linuxnext" ]; then
        # daily upstream linux-next
        kernelSource="https://git.kernel.org/pub/scm/linux/kernel/git/next/linux-next.git"
    elif [ "${CustomKernel}" == "upstream-stable" ]; then
        # kernel.org stable tree
        kernelSource="git://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git"
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
        apt install -y -qq linux-tools-generic/"$release"-proposed
        apt install -y -qq linux-cloud-tools-generic/"$release"-proposed
        apt install -y -qq linux-cloud-tools-common/"$release"-proposed
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
        apt-get clean all
        apt-get -y update >> $LOG_FILE 2>&1
        CheckInstallLockUbuntu
        apt-get install -yq linux-azure/"$release" >> $LOG_FILE 2>&1
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
        apt-get clean all
        apt-get -y update >> $LOG_FILE 2>&1
        CheckInstallLockUbuntu
        apt-get install -yq linux-azure-edge/"$release" >> $LOG_FILE 2>&1
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
            LogMsg "Enabling ppa repository..."
            DEBIAN_FRONTEND=noninteractive add-apt-repository --yes ppa:canonical-kernel-team/ppa
            apt -y update >> $LOG_FILE 2>&1
            LogMsg "Installing linux-image-generic from proposed repository."
            apt -y --fix-missing upgrade >> $LOG_FILE 2>&1
            kernelInstallStatus=$?
        fi
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
        apt -y update
        CheckInstallLockUbuntu

        LogMsg "Adding packages required by the kernel."
        apt install -y binutils

        LogMsg "Removing packages that do not allow the kernel to be installed"
        apt remove -y grub-legacy-ec2

        customKernelFilesUnExpanded="${CustomKernel#$LOCAL_FILE_PREFIX}"
        if [[ "${customKernelFilesUnExpanded}" == *'*.deb'* ]]; then
            CheckInstallLockUbuntu
            apt-get remove -y linux-cloud-tools-common
            image_file=$(ls -1 ${packageDir}/*image* | grep -v "dbg" | sed -n 1p)
        else
            image_file=$(ls -1 ${packageDir}/*.deb* | grep -v "dbg" | sed -n 1p)
        fi

        LogMsg "Installing ${image_file}"
        CheckInstallLockUbuntu
        eval "dpkg -i --force-overwrite ${packageDir}/*.deb >> $LOG_FILE 2>&1"
        eval "apt install -f -y >> $LOG_FILE 2>&1"
        kernelInstallStatus=$?

        release_publisher=$(cat /etc/issue | head -n 1 | awk '{print $1}')
        if [ "${release_publisher}"x == "Debian"x ]; then
            publisher_string="Debian GNU\/Linux"
        else
            publisher_string="Ubuntu"
        fi

        LogMsg "Configuring the correct kernel boot order"
        if [[ $kernelInstallStatus -eq 0 && "${image_file}" != '' ]]; then
            kernel_identifier=$(dpkg-deb --info "${image_file}" | grep 'Package: ' | grep -o "image.*")
            kernel_identifier=${kernel_identifier#image-}
            sed -i.bak "s/GRUB_DEFAULT=.*/GRUB_DEFAULT='Advanced options for $publisher_string>$publisher_string, with Linux $kernel_identifier'/g" /etc/default/grub
            update-grub
        else
            msg="Kernel correct boot order could not be set."
            kernelInstallStatus=1
            LogErr "$msg"
        fi

        if [ $kernelInstallStatus -ne 0 ]; then
            LogMsg "CUSTOM_KERNEL_FAIL"
            SetTestStateFailed
        else
            LogMsg "CUSTOM_KERNEL_SUCCESS"
            DEBIAN_FRONTEND=noninteractive apt -y remove linux-image-$(uname -r)
            rm -rf ${packageDir}/*.deb
            SetTestStateCompleted
        fi
    elif [[ $CustomKernel == *.rpm ]]; then
        LogMsg "Custom Kernel:$CustomKernel"
        case "$DISTRO_NAME" in
            oracle|rhel|centos)
                KERNEL_CONFLICTING_PACKAGES="hypervvssd hypervkvpd hypervfcopyd hyperv-daemons hyperv-tools kernel-headers"
                ;;
            suse|opensuse|sles)
                KERNEL_CONFLICTING_PACKAGES="hyper-v"
                ;;
        esac
        customKernelFilesUnExpanded="${CustomKernel#$LOCAL_FILE_PREFIX}"
        custom_kernel_version=$(rpm -qp --queryformat='%{Version}-%{Release}.%{Arch}\n' ${customKernelFilesUnExpanded})
        if [ "$custom_kernel_version" = "$(uname -r)" ]; then
            LogMsg "CUSTOM_KERNEL_ALREADY_INSTALLED"
            SetTestStateCompleted
            exit 0
        fi
        LogMsg "Removing packages that do not allow the kernel to be installed"
        if [[ "${customKernelFilesUnExpanded}" == *'*.rpm'* ]]; then
            LogMsg "Removing: ${KERNEL_CONFLICTING_PACKAGES}"
            remove_package "${KERNEL_CONFLICTING_PACKAGES}"
        fi

        LogMsg "Installing ${customKernelFilesUnExpanded}"
        eval "rpm -ivh $customKernelFilesUnExpanded >> $LOG_FILE 2>&1"
        kernelInstallStatus=$?

        LogMsg "Configuring the correct kernel boot order"
        sed -i 's%GRUB_DEFAULT=.*%GRUB_DEFAULT=0%' /etc/default/grub

        GetGuestGeneration
        if [ "$os_GENERATION" = "2" ]; then
            NEW_GRUB_CFG_FILE="$(find /boot/efi -name 'grub.cfg')" || "/boot/efi/EFI/grub.cfg"
        else
            NEW_GRUB_CFG_FILE="$(find /boot/grub* -name 'grub.cfg')" || "/boot/grub2/grub.cfg"
        fi
        LogMsg "Updating grub config: $NEW_GRUB_CFG_FILE"
        if [ ! -f "$NEW_GRUB_CFG_FILE" ]; then
            check_exit_status "Grub config $NEW_GRUB_CFG_FILE does not exist." "exit"
        fi

        grub2-mkconfig -o "$NEW_GRUB_CFG_FILE"

        SetTestStateCompleted
        if [ $kernelInstallStatus -ne 0 ]; then
            LogMsg "CUSTOM_KERNEL_FAIL"
            SetTestStateFailed
        else
            LogMsg "CUSTOM_KERNEL_SUCCESS"
            SetTestStateCompleted
            rpm -e kernel-$(uname -r)
            grub2-set-default 0
            rm -rf *.rpm
        fi
    fi
    if [[ ${CustomKernel} == "linuxnext" ]] || [[ ${CustomKernel} == "netnext" ]] || \
        [[ ${CustomKernel} == "upstream-stable" ]] || [[ ${CustomKernel} == *.tar.gz ]] || \
        [[ $CustomKernel = *.tar ]]; then
        LogMsg "Custom Kernel:$CustomKernel"
        Install_Build_Deps
        if [[ $CustomKernel = *tar.gz || $CustomKernel = *.tar ]]; then
            sourceDir=$tarDestination
        else
            sourceDir=$(Get_Upstream_Source "." "$kernelSource")
        fi
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
