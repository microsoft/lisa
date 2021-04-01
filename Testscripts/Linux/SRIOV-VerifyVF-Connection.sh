#!/bin/bash

# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
# Description:
#   Basic SR-IOV test checks connectivity SR-IOV between two VMs
#   Steps:
#   1. Verify/install pciutils package
#   2. Using the lspci command, examine the NIC with SR-IOV support
#   3. Check network capability
#   4. Send a 1GB file from VM1 to VM2
# Note: This script can handle multiple SR-IOV interfaces
#
########################################################################
remote_user="root"
if [ ! -e sriov_constants.sh ]; then
    cp /${remote_user}/sriov_constants.sh .
fi

# Source SR-IOV_Utils.sh. This is the script that contains all the
# SR-IOV basic functions (checking drivers, checking VFs, assigning IPs)
. SR-IOV-Utils.sh || {
    echo "ERROR: unable to source SR-IOV_Utils.sh!"
    echo "TestAborted" > state.txt
    exit 0
}

function version_lt() { test "$(echo "$@" | tr " " "\n" | sort -rV | head -n 1)" != "$1"; }

MIN_VERSION_SUPPORTED="6.7"

if [ $DISTRO_NAME == "centos" ] || [ $DISTRO_NAME == "rhel" ] || [ $DISTRO_NAME == "oracle" ]; then
    if version_lt $DISTRO_VERSION $MIN_VERSION_SUPPORTED ; then
        LogErr "SRIOV is not supported for Distro's below $MIN_VERSION_SUPPORTED, Test skipped!"
        SetTestStateSkipped
        exit 0
    fi
fi

# Check if Extra NICs have ips
if [[ "$NIC_COUNT" -gt 1 ]];then
    SERVER_NIC_IPs=($(ip add show | grep -v SLAVE | grep BROADCAST | sed 's/:/ /g' | awk '{print $2}'))
    for SERVER_NIC in "${SERVER_NIC_IPs[@]}"
    do
        server_ip_address=$(ip addr show $SERVER_NIC | grep "inet\b")
        if [[ -z "$server_ip_address" ]] ; then
            pkill dhclient
            sleep 3
            timeout 20 dhclient $SERVER_NIC
            server_ip_address=$(ip addr show $SERVER_NIC | grep "inet\b")
            if [[  -z "$server_ip_address"  ]] ; then
                LogMsg "NIC $SERVER_NIC doesn't have ip even after running dhclient"
                LogMsg "Server ifconfig $(ip a)"
                SetTestStateFailed
                exit 0
            fi
        fi
    done
    CLIENT_NIC_IPs=$(ssh root@"$VF_IP2" "ip add show | grep -v SLAVE | grep BROADCAST | sed 's/:/ /g' | awk '{print \$2}'")
    CLIENT_NIC_IPs=($CLIENT_NIC_IPs)
    for CLIENT_NIC in "${CLIENT_NIC_IPs[@]}"
    do
        client_ip_address=$(ssh root@"$VF_IP2" "ip addr show $CLIENT_NIC | grep 'inet\b'")
        if [[ -z "$client_ip_address" ]] ; then
            ssh root@"${VF_IP2}" "pkill dhclient"
            sleep 3
            ssh root@"${VF_IP2}" "timeout 20 dhclient $CLIENT_NIC"
            client_ip_address=$(ssh root@"$VF_IP2" "ip addr show $CLIENT_NIC | grep 'inet\b'")
            if [[ -z "$client_ip_address" ]] ; then
                LogMsg "NIC $CLIENT_NIC doesn't have ip even after running dhclient"
                client_if_config=$(ssh root@"$VF_IP2" "ip a")
                LogMsg "Client ifconfig ${client_if_config}"
                SetTestStateFailed
                exit 0
            fi
        fi
    done
    LogMsg "Extra NICs have ips"
fi

# Check if the SR-IOV driver is in use
VerifyVF
if [ $? -ne 0 ]; then
    LogErr "VF is not loaded! Make sure you are using compatible hardware"
    SetTestStateFailed
    exit 0
fi

if [ "$disable_enable_pci" = "yes" ]; then
    # call function with param SRIOV
    if ! DisableEnablePCI "SR-IOV"; then
        LogErr "Could not disable and reenable pci device."
        SetTestStateFailed
        exit 0
    fi
fi

# Create an 1gb file to be sent from VM1 to VM2
Create1Gfile
if [ $? -ne 0 ]; then
    LogErr "Could not create the 1gb file on VM1!"
    SetTestStateFailed
    exit 0
fi

# Check if the VF count inside the VM is the same as the expected count
vf_count=$(get_vf_count)
if [ "$vf_count" -ne "$NIC_COUNT" ]; then
    LogErr "Expected VF count: $NIC_COUNT. Actual VF count: $vf_count"
    SetTestStateFailed
    exit 0
fi
UpdateSummary "Expected VF count: $NIC_COUNT. Actual VF count: $vf_count"

__iterator=1
__ip_iterator_1=1
__ip_iterator_2=2

LogMsg  "List all network interfaces: $(ifconfig -a)"

# Ping and send file from VM1 to VM2
while [ $__iterator -le "$vf_count" ]; do
    # Extract VF_IP values
    ip_variable_name="VF_IP$__ip_iterator_1"
    static_IP_1="${!ip_variable_name}"
    ip_variable_name="VF_IP$__ip_iterator_2"
    static_IP_2="${!ip_variable_name}"

    synthetic_interface_vm_1=$(ip addr | grep $static_IP_1 | awk '{print $NF}')
    LogMsg  "Synthetic interface: $synthetic_interface_vm_1"

    if [[ -z ${synthetic_interface_vm_1} ]];then
        LogErr "Unable to detect the synthetic interface for $static_IP_1"
        SetTestStateFailed
        exit 0
    fi

    if [[ $DISTRO_VERSION =~ ^6\. ]]; then
        synthetic_MAC=$(ip link show ${synthetic_interface_vm_1} | grep ether | awk '{print $2}')
        vf_interface_vm_1=$(grep -il ${synthetic_MAC} /sys/class/net/*/address | grep -v $synthetic_interface_vm_1 | sed 's/\// /g' | awk '{print $4}')
    else
        if [[ -d /sys/firmware/efi ]]; then
        # This is the case of VM gen 2
            vf_interface_vm_1=$(find /sys/devices/* -name "*${synthetic_interface_vm_1}" | grep pci | sed 's/\// /g' | awk '{print $11}')
        else
        # VM gen 1 case
            vf_interface_vm_1=$(find /sys/devices/* -name "*${synthetic_interface_vm_1}" | grep pci | sed 's/\// /g' | awk '{print $12}')
        fi
    fi
    LogMsg "Virtual function: $vf_interface_vm_1"

    if [[ -z ${vf_interface_vm_1} ]];then
        LogErr "Unable to detect the VF interface for $synthetic_interface_vm_1"
        SetTestStateFailed
        exit 0
    fi

    # Ping the remote host
    i=0
    ping_exit_code=1
    while [ $i -lt 4 ]
    do
        i=$(($i+1))
        sleep 10
        ping -c 11 "$static_IP_2" > "$static_IP_2.log" 2>&1
        ping_exit_code=$?
        LogMsg "Attempt #$i to ping $VF_IP2 through $synthetic_interface_vm_1"
        if [ "$ping_exit_code" == 0 ]; then
            LogMsg "Successfully pinged $VF_IP2 through $synthetic_interface_vm_1"
            break
        fi
    done

    if [ "$ping_exit_code" == 1 ]; then
        LogErr "Unable to ping $VF_IP2 through $synthetic_interface_vm_1"
        SetTestStateFailed
        exit 0
    fi

    # Get the VF name from VM2
    cmd_to_send="ip addr | grep \"$static_IP_2\" | awk '{print \$NF}'"
    synthetic_interface_vm_2=$(ssh -i "$HOME"/.ssh/"$SSH_PRIVATE_KEY" -o StrictHostKeyChecking=no "$remote_user"@"$static_IP_2" "$cmd_to_send")
    if [[ $DISTRO_VERSION =~ ^6\. ]]; then
        synthetic_MAC_command="ip link show "${synthetic_interface_vm_2}" | grep ether | awk '{print \$2}'"
        synthetic_MAC=$(ssh -i "$HOME"/.ssh/"$SSH_PRIVATE_KEY" -o StrictHostKeyChecking=no "$remote_user"@"$static_IP_2" "$synthetic_MAC_command")
        cmd_to_send="grep -il ${synthetic_MAC} /sys/class/net/*/address | grep -v "${synthetic_interface_vm_2}" | sed 's/\// /g' | awk '{print \$4}'"
    else
        if [[ -d /sys/firmware/efi ]]; then
        # This is the case of VM gen 2
            cmd_to_send="find /sys/devices/* -name "*${synthetic_interface_vm_2}" | grep pci | sed 's/\// /g' | awk '{print \$11}'"
        else
        # VM gen 1 case
            cmd_to_send="find /sys/devices/* -name "*${synthetic_interface_vm_2}" | grep pci | sed 's/\// /g' | awk '{print \$12}'"
        fi
    fi
    vf_interface_vm_2=$(ssh -i "$HOME"/.ssh/"$SSH_PRIVATE_KEY" -o StrictHostKeyChecking=no "$remote_user"@"$static_IP_2" "$cmd_to_send")

    # Additional information for capturing tx and rx packet in case of failure.
    rx_value1=$(ssh -i "$HOME"/.ssh/"$SSH_PRIVATE_KEY" -o StrictHostKeyChecking=no "$remote_user"@"$static_IP_2" cat /sys/class/net/"${vf_interface_vm_2}"/statistics/rx_packets)
    tx_value1=$(cat /sys/class/net/"${vf_interface_vm_1}"/statistics/tx_packets)
    LogMsg "Packet count before sending the file: TX($tx_value1) RX($rx_value1)"

    # Send 1GB file from VM1 to VM2 via eth1
    output_file_path=$(find / -name $output_file)
    # Capture the md5sum of the file
    hash_val_tx=$(md5sum $output_file_path | awk '{print $1}')
    scp -i "$HOME"/.ssh/"$SSH_PRIVATE_KEY" -o StrictHostKeyChecking=no "$output_file_path" "$remote_user"@"$static_IP_2":/tmp/"$output_file"
    if [ 0 -ne $? ]; then
        LogErr "Unable to send the file from VM1 to VM2 ($static_IP_2)"
        SetTestStateFailed
        exit 0
    else
        LogMsg "Successfully sent $output_file to $VF_IP2"
    fi

    tx_value2=$(cat /sys/class/net/"${vf_interface_vm_1}"/statistics/tx_packets)
    rx_value2=$(ssh -i "$HOME"/.ssh/"$SSH_PRIVATE_KEY" -o StrictHostKeyChecking=no "$remote_user"@"$static_IP_2" cat /sys/class/net/"${vf_interface_vm_2}"/statistics/rx_packets)
    # Capture the md5sum of the recieved file
    hash_val_rx=$(ssh -i "$HOME"/.ssh/"$SSH_PRIVATE_KEY" -o StrictHostKeyChecking=no "$remote_user"@"$static_IP_2" md5sum /tmp/$output_file | awk '{print $1}')
    LogMsg "Packet count after sending the file: TX($tx_value2) RX($rx_value2)"

    LogMsg "tx hash ($hash_val_tx) rx hash ($hash_val_rx)"
    if [[ $hash_val_tx -ne $hash_val_rx ]];then
        LogErr "Transfered file is corrupted"
        SetTestStateFailed
        exit 0
    fi

    UpdateSummary "Successfully sent file from VM1 to VM2 through $synthetic_interface_vm_1"

    __ip_iterator_1=$(($__ip_iterator_1 + 2))
    __ip_iterator_2=$(($__ip_iterator_2 + 2))
    : $((__iterator++))
done

LogMsg "Updating test case state to completed"
SetTestStateCompleted
exit 0
