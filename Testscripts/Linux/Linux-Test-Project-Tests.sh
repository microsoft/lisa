#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

########################################################################
#
# Description:
#    This script installs and runs Linux Test Project(LTP) on a guest VM
#
#    Steps:
#    1. Installs dependencies
#    2. Compiles and installs LTP
#    3. Runs LTP in lite mode
#    4. Collects results
#
########################################################################
# Source utils.sh
. utils.sh || {
    echo "Error: unable to source utils.sh!"
    echo "TestAborted" > state.txt
    exit 0
}

# Source constants file and initialize most common variables
UtilsInit

TOP_BUILDDIR="/opt/ltp"
TOP_SRCDIR="$HOME/src"
LTP_RESULTS="$HOME/ltp-results.log"
LTP_OUTPUT="$HOME/ltp-output.log"
LTP_LITE_TESTS="math,fsx,ipc,mm,sched,pty,fs"
ltp_git_url="https://github.com/linux-test-project/ltp.git"

# The LTPROOT is used by some tests, e.g, block_dev test
export LTPROOT="/opt/ltp"

# Clear the old log
rm -f $LTP_RESULTS $LTP_OUTPUT

# Checks what Linux distro we are running on
GetDistro
update_repos

LogMsg "Installing dependencies"
common_packages=(m4 bison flex make gcc psmisc autoconf automake)
# RedHat 8 does no longer have the ntp package
if [[ $DISTRO != redhat_8 ]]; then
	common_packages+=(ntp)
fi
update_repos
install_package "${common_packages[@]}"

drive_name=$(bash get_data_disk_dev_name.sh)
LogMsg "Disk used: $drive_name"

case $DISTRO in
    "suse"*)
        suse_packages=(git-core db48-utils libaio-devel libattr1 \
            libcap-progs libdb-4_8 perl-BerkeleyDB)
        install_package "${suse_packages[@]}"
        ;;
    "ubuntu"* | "debian"*)
        deb_packages=(git libaio-dev libattr1 libcap-dev keyutils \
            libdb4.8 libberkeleydb-perl expect dh-autoreconf gdb \
            libnuma-dev quota genisoimage db-util unzip exfat-utils)
        install_package "${deb_packages[@]}"
        ;;
    "redhat"* | "centos"* | "fedora"*)
		rpm_packages=(git libaio-devel libattr libcap-devel libdb)
		# this must be revised later once epel_8 is available
		if [[ $DISTRO != redhat_8 ]]; then
			rpm_packages+=(db4-utils)
		fi
		install_epel
        install_package "${rpm_packages[@]}"
        ;;
    *)
        LogMsg "Unknown distro $DISTRO, continuing to try for RPM installation"
        ;;
esac

# Some CPU time is assigned to set real-time scheduler and it affects all cgroup test cases.
# The values for rt_period_us(1000000us or 1s) and rt_runtime_us (950000us or 0.95s).
# This gives 0.05s to be used by non-RT tasks.
rt_runtime_us=$(cat /sys/fs/cgroup/cpu/user.slice/cpu.rt_runtime_us)
if [ $rt_runtime_us -eq 0 ]; then
    echo "1000000" > /sys/fs/cgroup/cpu/cpu.rt_period_us
    echo "950000" > /sys/fs/cgroup/cpu/cpu.rt_runtime_us
    # Task-group setting
    echo "1000000" > /sys/fs/cgroup/cpu/user.slice/cpu.rt_period_us
    echo "950000" > /sys/fs/cgroup/cpu/user.slice/cpu.rt_runtime_us
fi

# Minimum 4M swap space is needed by some mmp test
swap_size=$(free -m | grep -i swap | awk '{print $2}')
if [ $swap_size -lt 4 ]; then
    dd if=/dev/zero of=/tmp/swap bs=1M count=1024
    mkswap /tmp/swap
    swapon /tmp/swap
fi

rm -rf "$TOP_SRCDIR"
mkdir -p "$TOP_SRCDIR"
cd "$TOP_SRCDIR"

# Fix hung_task_timeout_secs and blocked for more than 120 seconds problem
sysctl -w vm.dirty_ratio=10
sysctl -w vm.dirty_background_ratio=5
sysctl -p

# define regular stable releases in order to avoid unstable builds
# https://github.com/linux-test-project/ltp/tags
# 'ltp_version_git_tag' is passed from Test Definition in .\XML\TestCases\CommunityTests.xml.
# 'ltp_version_git_tag' default value is defined in .\XML\Other\ReplaceableTestParameters.xml
# You can run the ltp test with any tag using LISAv2's Custom Parameters feature.
if [[ $LTP_PACKAGE_URL == "" ]];then
    LogMsg "Cloning LTP"
    git clone "$ltp_git_url"
    TOP_SRCDIR="${HOME}/src/ltp"

    cd "$TOP_SRCDIR"
    if [[ "$ltp_version_git_tag" != "" || "$ltp_version_git_tag" != "master" ]]; then
        git checkout tags/"$ltp_version_git_tag"
    fi

    LogMsg "Configuring LTP..."
    # use autoreconf to match the installed package versions
    autoreconf -f 2>/dev/null
    make autotools 2>/dev/null

    test -d "$TOP_BUILDDIR" || mkdir -p "$TOP_BUILDDIR"
    cd "$TOP_BUILDDIR" && "$TOP_SRCDIR/configure"
    cd "$TOP_SRCDIR"
    ./configure 2>/dev/null

    LogMsg "Compiling LTP..."
    make -j $(nproc) all 2>/dev/null
    check_exit_status "Compile LTP" "exit"

    LogMsg "Installing LTP..."
    make -j $(nproc) install SKIP_IDCHECK=1 2>/dev/null
    check_exit_status "Install LTP" "exit"
else
    LogMsg "Download ltp package from: $LTP_PACKAGE_URL"
    curl "$LTP_PACKAGE_URL" --output "ltp.rpm"
    rpm --nodeps -ivh ltp.rpm
    check_exit_status "Install LTP RPM" "exit"
fi

cd "$TOP_BUILDDIR"

LogMsg "Running LTP..."
if [[ -n $drive_name ]]; then
       LTP_PARAMS="-p -q -l $LTP_RESULTS -o $LTP_OUTPUT -z $drive_name"
else
       LTP_PARAMS="-p -q -l $LTP_RESULTS -o $LTP_OUTPUT"
fi

if [[ "$SKIP_LTP_TESTS" != "" ]];then
    echo "Skipping tests: $SKIP_LTP_TESTS" >> ~/summary.log
    echo "$SKIP_LTP_TESTS" | tr "," "\n" > SKIPFILE
    LTP_PARAMS="-S ./SKIPFILE $LTP_PARAMS"
fi

if [[ "$CUSTOM_LTP_SUITES" != "" ]];then
    echo "Running custom suites: $CUSTOM_LTP_SUITES" >> ~/summary.log
    LTP_TEST_SUITE="lite"
    LTP_LITE_TESTS="$CUSTOM_LTP_SUITES"
fi

# LTP_TEST_SUITE is passed from the Test Definition xml or from command line when running LISAv2
# if the parameter is null, the test suite defaults to "lite"
if [[ "$LTP_TEST_SUITE" == "lite" || "$LTP_TEST_SUITE" == "" ]];then
    LTP_PARAMS="-f $LTP_LITE_TESTS $LTP_PARAMS"
    echo "Running ltp lite suite" >> ~/summary.log
elif [[ "$LTP_TEST_SUITE" == "full" ]];then
    echo "Running ltp full suite" >> ~/summary.log
fi

# LTP can request input if missing users/groups
# are detected, the yes command will handle the prompt.
yes | ./runltp $LTP_PARAMS 2>/dev/null

grep -A 5 "Total Tests" "$LTP_RESULTS" >> ~/summary.log
if grep FAIL "$LTP_OUTPUT" ; then
    echo "Failed Tests:" >> ~/summary.log
    grep FAIL "$LTP_OUTPUT" | cut -d':' -f 2- >> ~/summary.log
fi
echo "-----------LTP RESULTS----------------"
cat "$LTP_RESULTS" >> ~/TestExecution.log
echo "--------------------------------------"
echo "-----------LTP OUTPUT----------------"
cat "$LTP_OUTPUT" >> ~/TestExecution.log
echo "--------------------------------------"
collect_VM_properties
SetTestStateCompleted
exit 0
