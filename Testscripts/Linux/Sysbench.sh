#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

# Description:
#   This script installs and runs Sysbench tests on a guest VM
#   Steps:
#       1. Installs dependencies
#       2. Compiles and installs sysbench
#       3. Runs sysbench
#       4. Collects results
#
#   No optional parameters needed

ROOT_DIR="/root"

# For changing Sysbench version only the following parameter has to be changed
SYSBENCH_VERSION=1.0.9

function Cpu_Test ()
{
    LogMsg "Creating cpu.log and starting test."
    sysbench cpu --num-threads=1 run > /root/cpu.log
    if [ $? -ne 0 ]; then
        LogMsg "ERROR: Unable to execute sysbench CPU. Aborting..."
        SetTestStateAborted
    fi

    PASS_VALUE_CPU=$(cat /root/cpu.log |awk '/total time: / {print $3;}')
    if [ $? -ne 0 ]; then
        LogErr "Cannot find cpu.log."
        SetTestStateAborted
    fi

    RESULT_VALUE=$(echo ${PASS_VALUE_CPU} | head -c2)
    if  [ $RESULT_VALUE -lt 15 ]; then
        CPU_PASS=0
        UpdateSummary "CPU Test passed."
    else
        UpdateSummary "CPU Test failed"
        SetTestStateFailed
    fi

    LogMsg "$(cat /root/cpu.log)"
    return "$CPU_PASS"
}

function File_Io ()
{
    sysbench fileio --num-threads=1 --file-test-mode=$1 prepare > /dev/null 2>&1
    LogMsg "Preparing files to test $1..."

    sysbench fileio --num-threads=1 --file-test-mode=$1 run > /root/$1.log
    if [ $? -ne 0 ]; then
        LogErr "Unable to execute sysbench fileio mode $1. Aborting..."
        SetTestStateFailed
    else
        LogMsg "Running $1 tests..."
    fi

    PASS_VALUE_FILEIO=$(cat /root/$1.log |awk '/sum/ {print $2;}' | cut -d. -f1)
    if [ $? -ne 0 ]; then
        LogErr "Cannot find $1.log."
        SetTestStateFailed
    fi

    if  [ $PASS_VALUE_FILEIO -lt 12000 ]; then
        FILEIO_PASS=0
        UpdateSummary "Fileio Test -$1- passed with latency sum: $PASS_VALUE_FILEIO."
    else
        LogErr "Latency sum value is $PASS_VALUE_FILEIO. Test failed."
    fi

    sysbench fileio --num-threads=1 --file-test-mode=$1 cleanup
    LogMsg "Cleaning up $1 test files."

    LogMsg "$(cat /root/$1.log)"
    cat /root/$1.log >> /root/fileio.log
    rm /root/$1.log
    return "$FILEIO_PASS"
}

function Download_Sysbench() { 
    LogMsg "Cloning sysbench"
    wget https://github.com/akopytov/sysbench/archive/$SYSBENCH_VERSION.zip
    if [ $? -gt 0 ]; then
        LogErr "Failed to download sysbench."
        SetTestStateFailed
        exit 0
    fi

    yes | unzip $SYSBENCH_VERSION.zip
    if [ $? -gt 0 ]; then
        LogErr "Failed to unzip sysbench."
        SetTestStateFailed
        exit 0
    fi
}

function Install_Deps() {
    GetDistro

    case $OS_FAMILY in
        "Rhel")
            mkdir autoconf
            pushd autoconf
            wget http://ftp.gnu.org/gnu/autoconf/autoconf-2.69.tar.gz
            tar xvfvz autoconf-2.69.tar.gz
            pushd autoconf-2.69
            ./configure
            make
            make install
            popd

            yum_install "devtoolset-2-binutils automake libtool vim"
            popd
        ;;
        "Debian")
            apt_get_install "automake libtool pkg-config"
        ;;
        "Sles")
            zypper_install "vim"
        ;;
    esac

    pushd "$ROOT_DIR/sysbench-$SYSBENCH_VERSION"
    bash ./autogen.sh
    bash ./configure --without-mysql
    make
    make install
    if [ $? -ne 0 ]; then
        LogErr "Unable to install sysbench. Aborting..."
        SetTestStateAborted
        exit 0
    fi
    popd
    export PATH="/usr/local/bin:${PATH}"
    LogMsg "Sysbench installed successfully."
}

# Source utils.sh
. utils.sh || {
    LogErr "unable to source utils.sh!"
    SetTestStateAborted
    exit 0
}

UtilsInit

pushd $ROOT_DIR

Download_Sysbench

Install_Deps

popd

FILEIO_PASS=-1
CPU_PASS=-1

Cpu_Test

LogMsg "Testing fileio. Writing to fileio.log."
for test_item in ${TEST_FILE[*]}
do
    File_Io $test_item
    if [ $FILEIO_PASS -eq -1 ]; then
        LogErr "Test mode $test_item failed "
        SetTestStateFailed
    fi
done
UpdateSummary "Fileio tests passed."

if [ "$FILEIO_PASS" = "$CPU_PASS" ]; then
    UpdateSummary "All tests completed."
    SetTestStateCompleted
else
    LogMsg "Test Failed."
    SetTestStateFailed
fi
