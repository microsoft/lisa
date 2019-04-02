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
#    No optional parameters are needed
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

# Checks what Linux distro we are running on
GetDistro
update_repos

LogMsg "Installing dependencies"
common_packages=(git m4 bison flex make gcc psmisc autoconf automake)
update_repos
install_package "${common_packages[@]}"

case $DISTRO in
    "suse"*)
        suse_packages=(db48-utils libaio-devel libattr1 libcap-progs \
            libdb-4_8 perl-BerkeleyDB git-core)
        install_package "${suse_packages[@]}"
        ;;
    "ubuntu"* | "debian"*)
        deb_packages=(db-util libaio-dev libattr1 libcap-dev keyutils \
            libdb4.8 libberkeleydb-perl expect dh-autoreconf \
            libnuma-dev quota genisoimage gdb unzip exfat-utils)
        install_package "${deb_packages[@]}"
        ;;
    "redhat"* | "centos"* | "fedora"*)
        rpm_packages=(db48-utils libaio-devel libattr libcap-devel libdb)
        install_package "${rpm_packages[@]}"
        ;;
    *)
        LogMsg "Unknown distro $DISTRO, continuing to try for RPM installation"
        ;;
esac

rm -rf "$TOP_SRCDIR"
mkdir -p "$TOP_SRCDIR"
cd "$TOP_SRCDIR"

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
LTP_PARAMS="-p -q -l $LTP_RESULTS -o $LTP_OUTPUT -z /dev/sdc"

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
SetTestStateCompleted
exit 0
