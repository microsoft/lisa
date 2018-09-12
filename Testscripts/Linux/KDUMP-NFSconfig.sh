#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

#
# Source utils.sh to get more utils
# Get $DISTRO, LogMsg directly from utils.sh
#
. utils.sh || {
    echo "Error: unable to source utils.sh!"
    exit 0
}

#
# Source constants file and initialize most common variables
#
UtilsInit

Config_NFS_Rhel()
{
    # Modifying kdump.conf settings
    LogMsg "Configuring nfs (Rhel)..."

    yum_install nfs-utils
    if [ $? -ne 0 ]; then
        LogErr "Failed to install nfs."
        SetTestStateAborted
        exit 0
    fi

    grep "/mnt \*" /etc/exports
    if [ $? -ne 0 ]; then
        echo "/mnt *(rw,no_root_squash,sync)" >> /etc/exports
    fi

    service nfs restart
    if [ $? -ne 0 ]; then
        LogErr "Failed to restart nfs service."
        SetTestStateAborted
        exit 0
    fi

    #disable firewall in case it is running
    ls -l /sbin/init | grep systemd
    if [ $? -ne 0 ]; then
        service iptables stop
    else
        systemctl stop firewalld
    fi
}

Config_NFS_Sles()
{
    LogMsg "Configuring nfs (Sles)..."

    zypper_install nfs-kernel-server
    if [ $? -ne 0 ]; then
        LogErr "Failed to install nfs."
        SetTestStateAborted
        exit 0
    fi

    grep "/mnt \*" /etc/exports
    if [ $? -ne 0 ]; then
        echo "/mnt *(rw,no_root_squash,sync)" >> /etc/exports
    fi

    systemctl enable rpcbind.service
    systemctl restart rpcbind.service
    systemctl enable nfsserver.service
    systemctl restart nfsserver.service
    if [ $? -ne 0 ]; then
        LogErr "Failed to restart nfs service."
        SetTestStateAborted
        exit 0
    fi
}

Config_NFS_Debian()
{
    LogMsg "Configuring nfs (Ubuntu)..."
    apt-get update
    apt_get_install nfs-kernel-server
    if [ $? -ne 0 ]; then
        LogErr "Failed to install nfs."
        SetTestStateAborted
        exit 0
    fi

    grep "/mnt \*" /etc/exports
    if [ $? -ne 0 ]; then
        echo "/mnt *(rw,no_root_squash,sync)" >> /etc/exports
    fi

    service nfs-kernel-server restart
    if [ $? -ne 0 ]; then
        LogErr "Failed to restart nfs service."
        SetTestStateAborted
        exit 0
    fi
}

#######################################################################
#
# Main script body
#
#######################################################################

#
# Configure kdump - this has distro specific behaviour
#
GetDistro

Config_NFS_${OS_FAMILY}

rm -rf /mnt/*
SetTestStateCompleted
