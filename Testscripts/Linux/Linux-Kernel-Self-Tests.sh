#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

###############################################################################
#
# Description:
#    This script builds and runs Linux Kernel Self Tests(LKS) on a guest VM
#
#    Steps:
#    1. Installs dependencies
#    2. Installs kernel source code
#    3. Compiles Kselftests
#    4. Runs Kselftests
#    5. Collects results
#
# 1)If we set LKS_VERSION_GIT_TAG value, we use Kselftests from stable kernel of
#   this tag for avoiding unstable builds or non-uniform output format.
#   For Centos/Redhat or Ubuntu 16.04, there are some subsystems are failed to compile
#   for that some dependency packages' version is low. We use SKIP_TARGETS_COMPILE_FAIL_XXX
#   to skip these subsystems. There are some subsystems have some new features but the
#   test kernel don't have, we use SKIP_TARGETS_NONSUPPORT_XXX to skip them.
# 2)If LKS_VERSION_GIT_TAG is NULL, we use Kselftests from distro's own kernel. some subsystems
#   are unstable or compiled failed. We don't support SUSE.
# 3)If this test runs against custom kernel, we use Kselftests from linux-stable or
#   linux-next of the same version. We just skip $SKIP_TARGETS these targets. Some subsystems
#   are unstable or compiled failed.
# 4)We just support Ubuntu/Debian/Centos/Redhat/SUSE now, we will support other distros in the future.
#
###############################################################################
LKS_SRCDIR=""
MAKEFILE="./tools/testing/selftests/Makefile"

TARGETS="capabilities cgroup drivers/dma-buf efivarfs exec seccomp filesystems filesystems/binderfs \
firmware futex ima intel_pstate ipc ir kcmp lib membarrier mount mqueue netfilter nsfs proc ptrace pidfd\
rtc sigaltstack size splice static_keys sync sysctl user x86 zram"

# Skip these targets for they could hang or our scenario is not involved
SKIP_TARGETS="android breakpoints cpu-hotplug memory-hotplug vm powerpc"

# Skip these targets for they are failed to compile.
SKIP_TARGETS_COMPILE_FAIL_CENTOS7="proc"
SKIP_TARGETS_COMPILE_FAIL_UBUNTU16="proc"

# Skip these targets for the test kernel are non-support
SKIP_TARGETS_NONSUPPORT_UBUNTU16="drivers/dma-buf membarrier"
SKIP_TARGETS_NONSUPPORT_CENTOS7="drivers/dma-buf mount nsfs intel_pstate"
SKIP_TARGETS_NONSUPPORT_CENTOS8="drivers/dma-buf"
SKIP_TARGETS_NONSUPPORT_DEBIAN="drivers/dma-buf mount"
SKIP_TARGETS_NONSUPPORT_SUSE="membarrier drivers/dma-buf"

# Ignorable these failed tests for the kernel are non-support or test cases are unstable
IGNORABLE_FAIL_TESTS_UBUNTU16=("x86: test_syscall_vdso_32" "seccomp: seccomp_bpf")
IGNORABLE_FAIL_TESTS_CENTOS_7=("seccomp: seccomp_bpf" "x86: syscall_nt_64" "x86: sigreturn_64" "x86: fsgsbase_64" "x86: mpx-mini-test_64")
IGNORABLE_FAIL_TESTS_CENTOS_8=("proc: setns-dcache" "proc: proc-pid-vm" "seccomp: seccomp_bpf" \
                               "x86: check_initial_reg_state_32" "x86: mpx-mini-test_64" "x86: mpx-mini-test_32" \
                               "x86: check_initial_reg_state_64")
IGNORABLE_FAIL_TESTS_DEBIAN=("seccomp: seccomp_bpf")
IGNORABLE_FAIL_TESTS_SUSE=("seccomp: seccomp_bpf" "proc: proc-pid-vm" "proc: proc-self-map-files-001" \
                           "proc: proc-self-map-files-002" "proc: setns-dcache")

TOTAL_TARGETS=""
CUSTOM_KERNEL_FLAG="FALSE"
DISTRO_KERNEL_FLAG="FALSE"
VERSION_ID=""

ubuntu_src_git="git://git.launchpad.net/~canonical-kernel/ubuntu/+source/linux-azure/+git/"
next_kernel_src="https://git.kernel.org/pub/scm/linux/kernel/git/next/linux-next.git"
stable_kernel_src="git://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git"

###############################################################################
function install_dependencies() {
    LogMsg "Installing dependency packages"

    GetDistro
    update_repos

    case $DISTRO in
        ubuntu* | debian*)
            CheckInstallLockUbuntu
            deb_packages=(make git gcc flex bison clang llvm fuse gcc-multilib libfuse2 \
                        libc6-i386 libc6-dev-i386 libelf-dev libcap-ng-dev libfuse-dev \
                        libpopt-dev libnuma-dev libmount-dev libcap-dev build-essential \
                        pkg-config bc rsync)
            LogMsg "Dependency package names： ${deb_packages[@]}"
            install_package "${deb_packages[@]}" >> $BUILDING_LOG 2>&1
            ;;
        centos_7 | centos_8 | redhat_7 | redhat_8)
            rpm_packages=(make git gcc flex bison clang llvm fuse libcap-ng-devel popt-devel \
                        libcap-devel glibc-devel.*i686 fuse-devel elfutils-devel \
                        numactl-devel glibc-devel)
            if [[ $DISTRO != centos_8 ]]; then
                rpm_packages+=(libmount-devel glibc-static)
            fi
            install_epel
            LogMsg "Dependency package names： ${rpm_packages[@]}"
            install_package "${rpm_packages[@]}" >> $BUILDING_LOG 2>&1
            ;;
        suse*)
            suse_packages=(make git gcc flex bison fuse libcap-ng-devel fuse-devel popt-devel \
                         numactl libnuma-devel libmount-devel libcap-devel libcap-progs \
                         glibc-devel libelf-devel glibc-static)
            LogMsg "Dependency package names： ${suse_packages[@]}"
            install_package "${suse_packages[@]}" >> $BUILDING_LOG 2>&1
            ;;
         mariner)
            rpm_packages=(make git gcc flex bison clang llvm fuse libcap-ng-devel popt-devel \
                        libcap-devel fuse-devel elfutils-devel numactl glibc-devel build-essential \
                        rsync)
            LogMsg "Dependency package name: ${rpm_packages[@]}"
            install_package "${rpm_packages[@]}" >> $BUILDING_LOG 2>&1
            ;;
        *)
            LogErr "Unsupported distro: $DISTRO"
            return 1
            ;;
    esac
}

function download_custom_kernel() {
    cd /root
    if [[ $KERNEL_VERSION =~ "next" ]]; then
        version=${KERNEL_VERSION#*-}
        LogMsg "Kernel source git: $next_kernel_src"
        git clone $next_kernel_src
        check_exit_status "Clone next kernel source code" "exit"
        LKS_SRCDIR="/root/linux-next"
    else
        version=${KERNEL_VERSION%%[^.&^0-9]*}
        LogMsg "Kernel source git: $stable_kernel_src"
        git clone $stable_kernel_src
        check_exit_status "Clone stable kernel source code" "exit"
        LKS_SRCDIR="/root/linux"
    fi

    cd $LKS_SRCDIR
    tag=$(git tag | grep $version | head -1)
    LogMsg "Kernel tag: $tag"
    if [[ $tag != "" ]]; then
        git checkout -f $tag
    else
        LogErr "The kernel tag $version does not exist"
        return 1
    fi
}
# The kernel is distro kernel, we download distro kernel source code.
function download_distro_kernel() {
    # The kernel is distro kernel
    case $DISTRO in
        ubuntu*)
            #18.04  16.04  19.04
            ubuntu_codename="$(awk '/UBUNTU_CODENAME=/' /etc/os-release | sed 's/UBUNTU_CODENAME=//')"
            if [[ "$ubuntu_codename" != "" ]]; then
                src_code_git=$ubuntu_src_git$ubuntu_codename
                LogMsg "Kernel source git: $src_code_git"
                cd $HOMEDIR
                git clone $src_code_git
                check_exit_status "Clone kernel source code" "exit"
                LKS_SRCDIR=$HOMEDIR/$ubuntu_codename
                version=$(echo $KERNEL_VERSION | sed 's/-azure//')
            else
                LogErr "Get Ubuntu code name failed"
                return 1
            fi

            cd $LKS_SRCDIR
            tag=$(git tag | grep $version | head -1)
            LogMsg "Kernel tag: $tag"
            if [[ $tag != "" ]]; then
                git checkout -f $tag
            else
                LogErr "The kernel tag $version does not exist"
                return 1
            fi
            ;;
        debian*)
            #debian 10
            LogMsg "Kernel source: from linux-source package"
            CheckInstallLockUbuntu
            install_package "linux-source"
            cd /usr/src/
            ls linux-source-*.tar.xz
            if [ $? -ne 0 ]; then
                LogErr "Can't find linux source code"
                return 1
            fi

            xz -d linux-source-*.tar.xz
            tar -xf linux-source-*.tar -C $HOMEDIR
            LKS_SRCDIR="$HOMEDIR/linux-source-*"
            ;;
        centos*|redhat*)
            VERSION_ID=$(cat /etc/os-release | grep "VERSION_ID" | awk -F '"' '{print $2}' | awk -F '.' '{print $1}')
            src_version="c$VERSION_ID"
            LogMsg "Kernel source git: https://git.centos.org/git/rpms/kernel.git"
            LogMsg "Kernel source https://git.centos.org/git/centos-git-common.git"
            cd /root
            git clone https://git.centos.org/git/rpms/kernel.git
            git clone https://git.centos.org/git/centos-git-common.git
            if [[ -d "kernel" && -d "centos-git-common" ]]; then
                cd kernel
                git checkout "$src_version"
                ../centos-git-common/get_sources.sh
                if [ -d "SOURCES" ]; then
                    cd SOURCES
                    xz -d linux-*.tar.xz
                    tar -xf linux-*.tar
                    LKS_SRCDIR="/root/kernel/SOURCES/linux-*"
                else
                    LogErr "Can't find SOURCES directory"
                    return 1
                fi
            fi
            ;;
        *)
            LogErr "Unsupported distro $DISTRO"
            return 1
        ;;
    esac
}

# TOTAL_TARGETS is assiged a items string list in which items are in $1 but not in $2
# $1 == total targets
# $2 == skip targets
function skip_targets() {
    target_item=""
    for _tar in $1; do
        flag=0
        for _skip in $2; do
            if [ "$_tar"x  == "$_skip"x ]; then
                flag=1
                break
            fi
        done
        if [ $flag -eq 0 ]; then
            target_item=$target_item" $_tar"
        fi
    done
    TOTAL_TARGETS=$(echo $target_item | sed -e 's/^[ ]*//g')
}

# TOTAL_TARGETS is assiged a items string list of the intersection of $1 and $2
# $1 == total targets
# $2 == checked targets
function check_targets() {
    target_item=""
    for _tar in $2; do
        flag=0
        for _tar_item in $1; do
            if [ "$_tar"x  == "$_tar_item"x ]; then
                flag=1
                break
            fi
        done
        if [ $flag -eq 1 ]; then
            target_item=$target_item" $_tar"
        fi
    done
    TOTAL_TARGETS=$(echo $target_item | sed -e 's/^[ ]*//g')
}

function build_and_run_lks() {
    cd $LKS_SRCDIR

    if [ -f $MAKEFILE ]; then
        targets=$(cat $MAKEFILE | grep ^TARGETS | awk -F '=' '{print $2}' | sort -u | grep -v "^$")
        TOTAL_TARGETS="$targets"
        if [[ "$TARGETS" != "" ]]; then
            check_targets "$targets" "$TARGETS"
        fi

        if [[ "$CUSTOM_KERNEL_FLAG" != "TRUE" && "$DISTRO_KERNEL_FLAG" != "TRUE" ]]; then
            case $DISTRO in
            ubuntu*)
                #16.04
                VERSION_ID=$(cat /etc/os-release | grep VERSION_ID | sed 's/VERSION_ID=//g' | sed 's/\"//g' | awk -F '.' '{print $1}')
                if [ $[$VERSION_ID] -le 16 ]; then
                    LogMsg "Skip targets ($SKIP_TARGETS_COMPILE_FAIL_UBUNTU16 $SKIP_TARGETS_NONSUPPORT_UBUNTU16) for Ubuntu 16 or older version"
                    skip_targets "$TOTAL_TARGETS" "$SKIP_TARGETS_COMPILE_FAIL_UBUNTU16"" $SKIP_TARGETS_NONSUPPORT_UBUNTU16"
                fi
                ;;
            debian*)
                #debian 10 debian 9
                LogMsg "Skip targets ($SKIP_TARGETS_NONSUPPORT_DEBIAN) for Debian"
                skip_targets "$TOTAL_TARGETS" "$SKIP_TARGETS_NONSUPPORT_DEBIAN"
                ;;
            centos_7 | redhat_7)
                LogMsg "Skip targets ($SKIP_TARGETS_COMPILE_FAIL_CENTOS7 $SKIP_TARGETS_NONSUPPORT_CENTOS7) for Centos or Redhat"
                skip_targets "$TOTAL_TARGETS" "$SKIP_TARGETS_COMPILE_FAIL_CENTOS7 $SKIP_TARGETS_NONSUPPORT_CENTOS7"
                ;;
            centos_8 | redhat_8)
                LogMsg "Skip targets ($SKIP_TARGETS_NONSUPPORT_CENTOS8) for Centos or Redhat"
                skip_targets "$TOTAL_TARGETS" "$SKIP_TARGETS_NONSUPPORT_CENTOS8"
                ;;
            suse*)
                LogMsg "Skip targets ($SKIP_TARGETS_NONSUPPORT_SUSE) for suse"
                skip_targets "$TOTAL_TARGETS" "$SKIP_TARGETS_NONSUPPORT_SUSE"
                ;;
            mariner)
                LogMsg "Skip targets for mariner"
                ;;
            *)
                LogErr "Unknown distro $DISTRO"
                return 1
            ;;
            esac
        fi

        if [[ "$SKIP_TARGETS" != "" ]]; then
            LogMsg "Skip targets ($SKIP_TARGETS) for these targets may cause system hanging or our scenario is not involved"
            skip_targets "$TOTAL_TARGETS" "$SKIP_TARGETS"
        fi

        if [[ $DISTRO =~ "centos_8" ]]; then
            if [ -f "./tools/testing/selftests/x86/Makefile" ]; then
                sed -i "s/-static//" ./tools/testing/selftests/x86/Makefile
            fi
            if [ -f "./tools/testing/selftests/size/Makefile" ]; then
                sed -i "s/-static//" ./tools/testing/selftests/size/Makefile
            fi
        fi

        LogMsg "Total targets: $TOTAL_TARGETS"
        if [ $SUMMARY -eq 1 ]; then
            make -C tools/testing/selftests summary=1 TARGETS="$TOTAL_TARGETS" run_tests >> $LKS_OUTPUT 2>&1
        else
            make -C tools/testing/selftests TARGETS="$TOTAL_TARGETS" run_tests >> $LKS_OUTPUT 2>&1
        fi
    else
        LogErr "Makefile not found"
        return 1
    fi
}

function ignore_failed_tests_from_output() {
    local tests_list=("$@")
    local ignoreable_tests=""
    for test_name in "${tests_list[@]}"; do
        ignoreable_tests+="$test_name|"
    done
    ignoreable_tests=${ignoreable_tests%*|}
    LogMsg "Ignore tests: $ignoreable_tests"
    cat $LKS_OUTPUT | grep -E "^ok|^not ok" | sort -u | grep -vE "$ignoreable_tests" >> $LKS_RESULTS 2>&1
}

#######################################################################
#
# Main script body
#
#######################################################################
# Source utils.sh
. utils.sh || {
    echo "Error: unable to source utils.sh!"
    echo "TestAborted" > state.txt
    exit 0
}
HOMEDIR=$(pwd)
LKS_RESULTS="$HOMEDIR/lks-results.log"
LKS_OUTPUT="$HOMEDIR/lks-output.log"
BUILDING_LOG="$HOMEDIR/lks-building.log"
VM_LOG="$HOMEDIR/VM_properties.csv"
# Source constants file and initialize most common variables
UtilsInit

# Clear the old log
rm -f $LKS_RESULTS $LKS_OUTPUT

LogMsg "Installing dependencies"
install_dependencies
if [ $? -ne 0 ]; then
    LogErr "Failed to install dependency packages"
    SetTestStateSkipped
    exit 0
fi

LogMsg "Download LKS source code"
KERNEL_VERSION="$(uname -r)"
LogMsg "Kernel version: $KERNEL_VERSION"

# 1) If the kernel is custom kernel, we download next or stable kernel source code.
# 2) If $LKS_VERSION_GIT_TAG is set value, we download stable kernel of this tag for
#    avoiding unstable builds or non-uniform output format. 
#    'LKS_VERSION_GIT_TAG' is passed from Test Definition in .\XML\TestCases\CommunityTests.xml.
#    'LKS_VERSION_GIT_TAG' default value is defined in .\XML\Other\ReplaceableTestParameters.xml.
# 3) If the kernel is distro kernel, we download distro kernel source code.
if [[ $DISTRO =~ "ubuntu" && $KERNEL_VERSION != *azure*
    || $DISTRO =~ "debian" && $KERNEL_VERSION != *cloud*
    || $DISTRO =~ "centos" && $KERNEL_VERSION != *el*
    || $DISTRO =~ "redhat" && $KERNEL_VERSION != *el*
    || $DISTRO =~ "suse" && $KERNEL_VERSION != *azure* ]]; then
    download_custom_kernel
    if [ $? -ne 0 ]; then
        LogErr "Failed to download custom kernel source code"
        SetTestStateSkipped
        exit 0
    fi
    CUSTOM_KERNEL_FLAG="TRUE"
elif [[ "$LKS_VERSION_GIT_TAG" != "" ]]; then
    LogMsg "Kernel source git: $stable_kernel_src"
    LogMsg "Kernel git tag: $LKS_VERSION_GIT_TAG"
    cd /root
    git clone $stable_kernel_src
    check_exit_status "Clone stable kernel source code" "exit"
    LKS_SRCDIR="/root/linux"
    cd "$LKS_SRCDIR"
    git checkout "$LKS_VERSION_GIT_TAG"
else
    download_distro_kernel
    if [ $? -ne 0 ]; then
        LogErr "Failed to download distro kernel source code"
        SetTestStateAborted
        exit 0
    fi
    DISTRO_KERNEL_FLAG="TRUE"
fi

LogMsg "Building and running LKS tests..."
build_and_run_lks
if [ $? -ne 0 ]; then
    LogErr "Failed to build or run LKS"
    SetTestStateAborted
    exit 0
fi

LogMsg "Collecting test results..."
if [ -f $LKS_OUTPUT ]; then
    if [[ $DISTRO =~ "ubuntu" && $[$VERSION_ID] -le 16 ]]; then
        ignore_failed_tests_from_output "${IGNORABLE_FAIL_TESTS_UBUNTU16[@]}"
    elif [[ $DISTRO =~ "debian" ]]; then
        ignore_failed_tests_from_output "${IGNORABLE_FAIL_TESTS_DEBIAN[@]}"
    elif [[ $DISTRO =~ "centos_7" || $DISTRO =~ "redhat_7" ]]; then
        ignore_failed_tests_from_output "${IGNORABLE_FAIL_TESTS_CENTOS_7[@]}"
    elif [[ $DISTRO =~ "centos_8" || $DISTRO =~ "redhat_8" ]]; then
        ignore_failed_tests_from_output "${IGNORABLE_FAIL_TESTS_CENTOS_8[@]}"
    elif [[ $DISTRO =~ "suse" ]]; then
        ignore_failed_tests_from_output "${IGNORABLE_FAIL_TESTS_SUSE[@]}"
    else
        cat $LKS_OUTPUT | grep -E "^ok|^not ok" | sort -u >> $LKS_RESULTS 2>&1
    fi

    if [ -f $LKS_RESULTS ]; then
        pass_num=$(cat $LKS_RESULTS | grep "\[PASS\]" | wc -l)
        fail_num=$(cat $LKS_RESULTS | grep "\[FAIL\]" | wc -l)
        skip_num=$(cat $LKS_RESULTS | grep "\[SKIP\]" | wc -l)
        total_num=$(expr $pass_num + $fail_num + $skip_num)
    fi
    UpdateSummary "Total tests: $total_num"
    UpdateSummary "Pass tests: $pass_num Fail tests: $fail_num Skip tests: $skip_num"
else
    LogErr "Failed to run lks tests"
    SetTestStateAborted
    exit 0
fi

collect_VM_properties "$VM_LOG"
SetTestStateCompleted
exit 0
