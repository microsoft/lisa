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
    redhat*|centos*|oracle*|almalinux*|rockylinux*)
        echo "[packages-microsoft-com-azurecore]" | tee -a /etc/yum.repos.d/azurecore.repo
        echo "name=packages-microsoft-com-azurecore" | tee -a /etc/yum.repos.d/azurecore.repo
        echo "baseurl=https://packages.microsoft.com/yumrepos/azurecore/" | tee -a /etc/yum.repos.d/azurecore.repo
        echo "enabled=1" | tee -a /etc/yum.repos.d/azurecore.repo
        echo "gpgcheck=0" | tee -a /etc/yum.repos.d/azurecore.repo
    ;;
    ubuntu*|debian*)
        echo "deb [arch=amd64] http://packages.microsoft.com/repos/azurecore/ trusty main" | sudo tee -a /etc/apt/sources.list.d/azure.list
        echo "deb [arch=amd64] http://packages.microsoft.com/repos/azurecore/ xenial main" | sudo tee -a /etc/apt/sources.list.d/azure.list
        echo "deb [arch=amd64] http://packages.microsoft.com/repos/azurecore/ bionic main" | sudo tee -a /etc/apt/sources.list.d/azure.list

        wget -qO - https://packages.microsoft.com/keys/microsoft.asc | apt-key add -
        wget -qO - https://packages.microsoft.com/keys/msopentech.asc | apt-key add -
        if [[ $DISTRO == *debian* ]]; then
            install_package gnupg
        fi
    ;;
    suse*|opensuse*|sles*|sle_hpc*)
        zypper ar -t rpm-md -n "packages-microsoft-com-azurecore" --no-gpgcheck https://packages.microsoft.com/yumrepos/azurecore/ azurecore
    ;;
    *)
        LogErr "Distro not supported. Skipping test case..."
        UpdateSummary "Distro not supported. Skipping test case..."
        SetTestStateSkipped
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

output=$(sudo /usr/bin/mbinfo)
ret=$?
LogMsg "$output"

if [ $ret == 0 ]; then
    UpdateSummary "This OS image is compatible with Measured Boot."
    SetTestStateCompleted
else
    UpdateSummary "This OS image is not compatible with Measured Boot."
    SetTestStateFailed
fi

exit 0
