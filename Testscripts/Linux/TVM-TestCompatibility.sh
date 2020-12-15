#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

. utils.sh || {
    echo "Error: unable to source utils.sh!"
    echo "TestAborted" > state.txt
    exit 0
}

UtilsInit

GetDistro
case $DISTRO in
    redhat*|centos*|oracle*)
        echo "[packages-microsoft-com-azurecore]" | tee -a /etc/yum.repos.d/azurecore.repo
        echo "name=packages-microsoft-com-azurecore" | tee -a /etc/yum.repos.d/azurecore.repo
        echo "baseurl=https://packages.microsoft.com/yumrepos/azurecore/" | tee -a /etc/yum.repos.d/azurecore.repo
        echo "enabled=1" | tee -a /etc/yum.repos.d/azurecore.repo
        echo "gpgcheck=0" | tee -a /etc/yum.repos.d/azurecore.repo
    ;;
    ubuntu*|debian*)
        release=$(lsb_release -c -s)
        echo "deb [arch=amd64] http://packages.microsoft.com/repos/azurecore/ $release main" | sudo tee -a /etc/apt/sources.list.d/azure.list

        wget -qO https://packages.microsoft.com/keys/microsoft.asc | apt-key add microsoft.asc
        wget -qO https://packages.microsoft.com/keys/msopentech.asc | apt-key add msopentech.asc

    ;;
    suse*|opensuse*|sles*|sle_hpc*)
        zypper ar -t rpm-md -n "packages-microsoft-com-azurecore" --no-gpgcheck https://packages.microsoft.com/yumrepos/azurecore/ azurecore
    ;;
    *)
        LogErr "Distro not supported. Skipping test case..."
        UpdateSummary "Distro not supported. Skipping test case..."
        SetTestStateAborted
        exit 0
    ;;
esac

LogMsg "Trying to install azure-compatscanner package..."
update_repos
install_package "azure-compatscanner"

if [ ! -e /usr/bin/mbinfo ]; then
    LogErr "mbinfo tool is not on the system"
    SetTestStateAborted
    exit 0
fi


output=$(sudo mbinfo)
LogMsg "$output"

if [ $? == 0 ]; then
    UpdateSummary "This OS image is compatible with TVM."
    SetTestStateCompleted
else
    UpdateSummary "This OS image is not compatible with TVM."
    SetTestStateFailed
fi

exit 0
