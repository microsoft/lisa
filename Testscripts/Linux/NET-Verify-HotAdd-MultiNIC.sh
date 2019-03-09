#!/bin/bash

# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

. utils.sh || {
    echo "unable to source utils.sh!"
    exit 0
}

# Source constants file and initialize most common variables
UtilsInit


# Add_Nic ($eth_count)
function Add_Nic {
    eth_count=$1
    eth_name=$2

    LogMsg "Checking the eth_count"
    if [ $eth_count -ne 2 ]; then
        LogErr "VM should have two NICs now"
        SetTestStateAborted
        exit 0
    fi
    # Bring the new NIC online
    GetDistro
    LogMsg "OS_FAMILY=$OS_FAMILY"
    if [ "$OS_FAMILY" == "Rhel" ]; then
            LogMsg "Creating ifcfg-${eth_name}"
            cp /etc/sysconfig/network-scripts/ifcfg-eth0 /etc/sysconfig/network-scripts/ifcfg-${eth_name}
            sed -i -- "s/eth0/${eth_name}/g" /etc/sysconfig/network-scripts/ifcfg-${eth_name}
            sed -i -e "s/HWADDR/#HWADDR/" /etc/sysconfig/network-scripts/ifcfg-${eth_name}
            sed -i -e "s/UUID/#UUID/" /etc/sysconfig/network-scripts/ifcfg-${eth_name}
    elif [ "$OS_FAMILY" == "Sles" ]; then
            LogMsg "Creating ifcfg-${eth_name}"
            cp /etc/sysconfig/network/ifcfg-eth0 /etc/sysconfig/network/ifcfg-${eth_name}
            sed -i -- "s/eth0/${eth_name}/g" /etc/sysconfig/network/ifcfg-${eth_name}
            sed -i -e "s/HWADDR/#HWADDR/" /etc/sysconfig/network/ifcfg-${eth_name}
            sed -i -e "s/UUID/#UUID/" /etc/sysconfig/network/ifcfg-${eth_name}
    elif [ "$OS_FAMILY" == "Debian" ]; then
            echo "auto ${eth_name}" >> /etc/network/interfaces
            echo "iface ${eth_name} inet dhcp" >> /etc/network/interfaces
    else
        LogErr "Linux Distro not supported!"
        SetTestStateAborted
        exit 0
    fi

    LogMsg "Bringing up ${eth_name}"
    ifup ${eth_name}
    sleep 5
    # Verify the new NIC received an IP v4 address
    LogMsg "Verify the new NIC has an IPv4 address"
    ip addr show ${eth_name} | grep "inet\b" > /dev/null
    check_exit_status "${eth_name} is up"  "exit"
}

# Remove_Nic ($eth_count)
function Remove_Nic {
    eth_count=$1
    eth_name=$2
    if [ $eth_count -ne 1 ]; then
        LogErr "There are more than one eth devices"
        SetTestStateAborted
        exit 0
    fi
    # Clean up files & check linux log for errors
    GetDistro
    LogMsg "OS_FAMILY=$OS_FAMILY"
    if [ "$OS_FAMILY" == "Rhel" ]; then
            LogMsg "Cleaning up RHEL/CentOS/Fedora"
            rm -f /etc/sysconfig/network-scripts/ifcfg-${eth_name}
            cat /var/log/messages | grep "unable to close device (ret -110)"
            if [ $? -eq 0 ]; then
                LogErr "/var/log/messages reported netvsc throwed errors"
            fi
    elif [ "$OS_FAMILY" == "Sles" ]; then
            rm -f /etc/sysconfig/network/ifcfg-${eth_name}
            cat /var/log/messages | grep "unable to close device (ret -110)"
            if [ $? -eq 0 ]; then
                LogErr "/var/log/messages reported netvsc throwed errors"
            fi
    elif [ "$OS_FAMILY" == "Debian" ]; then
            sed -i -e "/auto ${eth_name}/d" /etc/network/interfaces
            sed -i -e "/iface ${eth_name} inet dhcp/d" /etc/network/interfaces
            cat /var/log/syslog | grep "unable to close device (ret -110)"
            if [ $? -eq 0 ]; then
                LogErr "/var/log/syslog reported netvsc throwed errors"
            fi
    else
        LogErr "Linux Distro not supported!"
        SetTestStateAborted
        exit 0
    fi
}

# Determine how many eth devices the OS sees
eth_count=$(ls -d /sys/class/net/eth* | wc -l)
LogMsg "eth_count = ${eth_count}"


# Get data about Linux Distribution
GetOSVersion

# Get the specific nic name as seen by the vm
eth_name=$(ip -o link show | awk -F': ' '{print $2}' | grep eth | sed -n 2p)

# Set eth_count based on the value of $1
case "$1" in
add)
    Add_Nic $eth_count $eth_name
    ;;
remove)
    Remove_Nic $eth_count $eth_name
    ;;
*)
    LogErr "Unknown argument of $1"
    SetTestStateAborted
    exit 0
    ;;
esac

exit 0