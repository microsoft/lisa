#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

##################################################################
#
# Description:
# This script compares LIS source version (#define HV_DRV_VERSION)
# with version retrieved from command modinfo
#
##################################################################

function check_lis_version
{
	version=$1
	sourceversion=$2
	LogMsg "Detected modinfo version is $version"
	LogMsg "Version found in source code is $sourceversion"
	if [ "$version" = "$sourceversion" ]
	then
		LogMsg "Detected version and Source version are same"
	else
		LogMsg "Detected version and Source version are different"
		updateSummary "LIS version check is failed"
		SetTestStateFailed
		exit 0
	fi
}

function check_lis_version_hex()
{
	version=$1
	sourceversion_hex=$2
	LogMsg "Detected modinfo version is $version"
	LogMsg "Version found in source code hex value :$sourceversion_hex"
	version1=$(echo "$version"|tr -d .)
	version_hex=$(echo "obase=16;ibase=10; $version1" | bc |tr -d '" "')
	if [ "$version_hex" = "$sourceversion_hex" ]
	then
		LogMsg "Detected version and Source version are same for hex value"
	else
		LogMsg "Detected version and Source version are different for hex value"
		updateSummary "LIS hex version check failed"
		SetTestStateFailed
		exit 0
	fi
}

# Source utils.sh
. utils.sh || {
	echo "ERROR: unable to source utils.sh!"
	echo "TestAborted" > state.txt
	exit 2
}

# Source constants file and initialize most common variables
UtilsInit
# Check wget
which wget > /dev/null 2>&1
if [ $? -ne 0 ]; then
    install_package wget
    check_exit_status "wget install" "exit"
fi

# To check LIS rpms are installed or not
rpm -qa | grep "kmod-microsoft-hyper-v" && rpm -qa | grep "microsoft-hyper-v"
if [ $? -ne 0 ]
then
    LogMsg "No LIS RPM's are detected. Skipping test."
    SetTestStateSkipped
    exit 0
else
    version=$(modinfo "hv_vmbus" | grep version: | head -1 | awk '{print $2}')
    for i in 5 6 7
    do
        rm -rf hv_compat.h
        wget https://raw.githubusercontent.com/LIS/lis-next/"$version"/hv-rhel$i.x/hv/include/linux/hv_compat.h
        check_exit_status "Download file hv_compat.h" "exit"
        sourceversion=$(grep 'define HV_DRV_VERSION' hv_compat.h|cut -d '"' -f 2)
        sourceversion_hex=$(grep 'define _HV_DRV_VERSION' hv_compat.h|cut -d ' ' -f 3|tr -d '0x')
        check_lis_version $version $sourceversion
        check_lis_version_hex $version $sourceversion_hex
    done
fi

UpdateSummary "LIS version check is success"
SetTestStateCompleted