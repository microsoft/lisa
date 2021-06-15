#!/bin/bash

# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

########################################################################
#
# Description:
#
# This script contains all SR-IOV related functions that are used
# in the SR-IOV test suite.
#
# iperf3 3.1.x or newer is required for the output logging features
#
########################################################################

# iperf3 download location
iperf3_version=3.2
iperf3_url=https://github.com/esnet/iperf/archive/$iperf3_version.tar.gz

. sriov_constants.sh || {
    echo "ERROR: unable to source sriov_constants.sh!"
    echo "TestAborted" > state.txt
    exit 2
}

# Source utils.sh
. utils.sh || {
    echo "ERROR: unable to source utils.sh!"
    echo "TestAborted" > state.txt
    exit 2
}

# Source constants file and initialize most common variables
UtilsInit

# Declare global variables
declare -i vfCount

#
# VerifyVF - check if the VF driver is use
#
VerifyVF()
{
    msg="ERROR: Failed to install pciutils"

    # Check for pciutils. If it's not on the system, install it
    lspci --version
    if [ $? -ne 0 ]; then
        LogMsg "INFO: pciutils not found. Trying to install it"
        update_repos
        install_package "pciutils"
        if [ $? -ne 0 ]; then
            LogMsg "$msg"
            SetTestStateFailed
            exit 1
        fi
    fi

    # Using lsmod command, verify if driver is loaded
    lsmod | grep 'mlx[4-5]_core\|mlx4_en\|ixgbevf'
    if [ $? -ne 0 ]; then
        # driver can be built-in, continuing to lspci
        LogErr "Neither mlx[4-5]_core\mlx4_en or ixgbevf drivers are in use!"
    fi

    # Using the lspci command, verify if NIC has SR-IOV support
    lspci -vvv | grep 'mlx[4-5]_core\|mlx4_en\|ixgbevf'
    if [ $? -ne 0 ]; then
        LogMsg "No Mellanox or Intel NIC with SR-IOV support found!"
        SetTestStateFailed
        exit 1
    fi

    if [ -z "$VF_IP1" ]; then
        vf_interface=$(ls /sys/class/net/ | grep -v 'eth0\|eth1\|lo' | head -1)
    else
        synthetic_interface=$(ip addr | grep "$VF_IP1" | awk '{print $NF}')
        if [[ $DISTRO_VERSION =~ ^6\. ]]; then
            synthetic_MAC=$(ip link show ${synthetic_interface} | grep ether | awk '{print $2}')
            vf_interface=$(grep -il ${synthetic_MAC} /sys/class/net/*/address | grep -v $synthetic_interface | sed 's/\// /g' | awk '{print $4}')
        else
            if [[ -d /sys/firmware/efi ]]; then
            # This is the case of VM gen 2
                vf_interface=$(find /sys/devices/* -name "*${synthetic_interface}" | grep pci | sed 's/\// /g' | awk '{print $11}')
            else
            # VM gen 1 case
                vf_interface=$(find /sys/devices/* -name "*${synthetic_interface}" | grep pci | sed 's/\// /g' | awk '{print $12}')
            fi
        fi
    fi

    ip addr show "$vf_interface"
    if [ $? -ne 0 ]; then
        LogErr "VF device $vf_interface was not found!"
        SetTestStateFailed
        exit 1
    fi


    return 0
}

#
# Create1Gfile - it creates a 1GB file that will be sent between VMs as part of testing
#
Create1Gfile()
{
    output_file=large_file

    if [ "${ZERO_FILE:-UNDEFINED}" = "UNDEFINED" ]; then
        file_source=/dev/urandom
    else
        file_source=/dev/zero
    fi

    if [ -d "$HOME"/"$output_file" ]; then
        rm -rf "$HOME"/"$output_file"
    fi

    if [ -e "$HOME"/"$output_file" ]; then
        rm -f "$HOME"/"$output_file"
    fi

    dd if=$file_source of="$HOME"/"$output_file" bs=1 count=0 seek=1G
    if [ 0 -ne $? ]; then
        LogErr "Unable to create file $output_file in $HOME"
        SetTestStateFailed
        exit 1
    fi

    LogMsg "Successfully created $output_file"
    return 0
}

#
# ConfigureVF - will set the given VF_IP(s) (from constants file)
# for each vf present
#
ConfigureVF()
{
    vfCount=$(find /sys/devices -name net -a -ipath '*vmbus*' | grep pci | wc -l)
    if [ "$vfCount" -eq 0 ]; then
        LogErr "No VFs are present in the Guest VM!"
        SetTestStateFailed
        exit 0
    fi

    __iterator=1
    __ipIterator=$1
    LogMsg "Iterator: $__iterator"

    GetDistro
    # Set static IPs for each vf created
    while [ $__iterator -le "$vfCount" ]; do
        LogMsg "Network config will start"

        # Extract vfIP value from constants.sh
        staticIP=$(cat sriov_constants.sh | grep IP"$__ipIterator" | head -1 | tr "=" " " | awk '{print $2}')
        broadcastAddress="${staticIP%.*}.255"

        case $DISTRO in
            ubuntu*)
                if [ -d /etc/netplan/ ]; then
                    __file_path="/etc/netplan/$__iterator-static-network.yaml"
                    rm -rf $__file_path
                    echo "network:" >> "$__file_path"
                    echo "    version: 2" >> "$__file_path"
                    echo "    ethernets:" >> "$__file_path"
                    echo "        eth$__iterator:" >> "$__file_path"
                    echo "            dhcp4: no" >> "$__file_path"
                    echo "            addresses: [$staticIP/24]" >> "$__file_path"
                else
                    __file_path="/etc/network/interfaces"
                    # Change /etc/network/interfaces
                    echo "auto eth$__iterator" >> $__file_path
                    echo "iface eth$__iterator inet static" >> $__file_path
                    echo "address $staticIP" >> $__file_path
                    echo "netmask $NETMASK" >> $__file_path
                fi
                ip link set eth$__iterator up
                ip addr add "${staticIP}"/"$NETMASK" broadcast $broadcastAddress dev eth$__iterator
            ;;
            suse*|sles*)
                __file_path="/etc/sysconfig/network/ifcfg-eth$__iterator"
                rm -f $__file_path

                # Replace the BOOTPROTO, IPADDR and NETMASK values found in ifcfg file
                echo "DEVICE=eth$__iterator" >> $__file_path
                echo "NAME=eth$__iterator" >> $__file_path
                echo "BOOTPROTO=static" >> $__file_path
                echo "IPADDR=$staticIP" >> $__file_path
                echo "NETMASK=$NETMASK" >> $__file_path
                echo "STARTMODE=auto" >> $__file_path

                ip link set eth$__iterator up
                ip addr add "${staticIP}"/"$NETMASK" broadcast $broadcastAddress dev eth$__iterator
            ;;

            redhat_*|centos_*|almalinux*)
                __file_path="/etc/sysconfig/network-scripts/ifcfg-eth$__iterator"
                rm -f $__file_path

                # Replace the BOOTPROTO, IPADDR and NETMASK values found in ifcfg file
                echo "DEVICE=eth$__iterator" >> $__file_path
                echo "NAME=eth$__iterator" >> $__file_path
                echo "BOOTPROTO=static" >> $__file_path
                echo "IPADDR=$staticIP" >> $__file_path
                echo "NETMASK=$NETMASK" >> $__file_path
                echo "ONBOOT=yes" >> $__file_path

                ip link set eth$__iterator up
                ip addr add "${staticIP}"/"$NETMASK" broadcast $broadcastAddress dev eth$__iterator
            ;;

            mariner)
                __file_path="/etc/systemd/network/$__iterator-static-en.network"
                rm -f $__file_path

                echo "[Match]" >> $__file_path
                echo "Name=eth$__iterator" >> $__file_path
                echo "[Network]" >> $__file_path
                echo "Address=$staticIP/24" >> $__file_path

                ip link set eth$__iterator up
                ip addr add "${staticIP}"/"$NETMASK" broadcast $broadcastAddress dev eth$__iterator
            ;;

            *)
                LogErr "$DISTRO does not support in the function call"
                SetTestStateFailed
                exit 0
            ;;
        esac
        LogMsg "Network config file path: $__file_path"

        __ipIterator=$(($__ipIterator + 2))
        : $((__iterator++))
    done

    return 0
}

#
# InstallDependencies - install wget and iperf3 if not present
#
InstallDependencies()
{
    msg="ERROR: Failed to install wget"

    # Enable broadcast listening
    echo 0 >/proc/sys/net/ipv4/icmp_echo_ignore_broadcasts

    # Stop firewall
    stop_firewall

    lspci --version
    if [ $? -ne 0 ]; then
        LogMsg "INFO: pciutils not found. Trying to install it"
        update_repos
        install_package "pciutils"
        if [ $? -ne 0 ]; then
            LogMsg "$msg"
            SetTestStateFailed
            exit 1
        fi
    fi

    wget -V > /dev/null 2>&1
    if [ $? -ne 0 ]; then
        update_repos
        install_package "wget"
        if [ $? -ne 0 ]; then
            LogMsg "$msg"
            SetTestStateFailed
            exit 1
        fi
    fi

    # Check if iPerf3 is already installed
    iperf3 -v > /dev/null 2>&1
    if [ $? -ne 0 ] && [[ $(detect_linux_distribution) != coreos ]] && [[ $(detect_linux_distribution) != mariner ]]; then
        update_repos
        gcc -v
        if [ $? -ne 0 ]; then
            install_package "gcc"
        fi
        make -v
        if [ $? -ne 0 ]; then
            install_package "make"
        fi
        wget $iperf3_url
        if [ $? -ne 0 ]; then
            LogErr "Failed to download iperf3 from $iperf3_url"
            SetTestStateFailed
            exit 1
        fi

        tar xf $iperf3_version.tar.gz
        pushd iperf-$iperf3_version

        ./configure; make; make install
        # update shared libraries links
        ldconfig
        popd
        PATH="$PATH:/usr/local/bin"
        iperf3 -v > /dev/null 2>&1
        if [ $? -ne 0 ]; then
            LogErr "Failed to install iperf3"
            SetTestStateFailed
            exit 1
        fi
    else
        install_iperf3
    fi

    return 0
}

#
# DisableNetworkManager-SRIOV - Disable the NetworkManager permanently if it's running
#
function DisableNetworkManager-SRIOV() {
    systemctl status NetworkManager | grep "Active:[ ]*active"
    if [ $? -eq 0 ]; then
        systemctl stop NetworkManager
        systemctl disable NetworkManager
    fi
}
