#!/bin/bash

# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

# ETHTOOL-OFFLOADING-SETTING.sh
# Description:
#    1. Run TCP traffic with iperf3 between server and client VMs during whole test.
#    2. Get the default offloading state on the client VM.
#    3. Disable/enable the VF on the client VM.
#    4. Check the offloading state which is the same to the default state on the client VM.
#    5. Set and check scatter-gather feature to be tunable on the client VM.
#    6. Disable/enable the VF again and check the scatter-gather feature setting persists on VF.
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

# Check if ethtool exist and install it if not
if ! VerifyIsEthtool; then
    LogErr "Could not find ethtool in the VM"
    SetTestStateFailed
    exit 0
fi

# check_feature_status
# $1: eth device name
# $2: feature name
# $3: status(on/off)
function check_feature_status() {
    on_or_off=$(ethtool -k $1 2>&1 | grep "^$2" | awk {'print $2'})
    if [[ "$on_or_off" != "$3" ]];then
        LogErr "The $2 is expected $3, but it returned $on_or_off."
        SetTestStateFailed
        exit 0
    else
        LogMsg "Returned the expected value, $on_or_off"
    fi
}

# set_feature_status
# $1: eth device name
# $2: feature device name
# $3: status(on/off)
function set_feature_status() {
    result=$(ethtool -K $1 $2 $3 2>&1)
    if [[ "$result" = *"Could not change any device features"* ]]; then
        LogErr "$result"
        LogErr "The kernel doesn't support $2 feature"
        SetTestStateFailed
        exit 0
    else
        LogMsg "Successfully set the value $3 of $3 in the device $1."
    fi
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

# Only upstream with "Enable sg as tunable, sync offload settings to VF NIC" patch supports syncing offloading
# if no [fixed] string next to tx-scatter-gather in ethtool -k, the kernel has the right patches.
patch_filter=$(ethtool -k eth0 | grep -i tx-scatter-gather:)
if [[ $patch_filter == *"[fixed]" ]]; then
    LogErr "Syncing offloading is not supported or missed the required patches for $(uname -r), Test skipped!"
    SetTestStateSkipped
    exit 0
fi

# Check if Extra NICs have ips
if [[ "$NIC_COUNT" -gt 1 ]];then
    SERVER_NIC_IPs=($(ip add show | grep -v SLAVE | grep BROADCAST | sed 's/:/ /g' | awk '{print $2}'))
    for SERVER_NIC in "${SERVER_NIC_IPs[@]}"
    do
        server_ip_address=$(ip addr show $SERVER_NIC | grep 'inet\b')
        if [[ -z "$server_ip_address" ]] ; then
            pkill dhclient
            sleep 1
            timeout 10 dhclient $SERVER_NIC
            server_ip_address=$(ip addr show $SERVER_NIC | grep 'inet\b')
            if [[  -z "$server_ip_address"  ]] ; then
                LogMsg "NIC $SERVER_NIC doesn't have ip even after running dhclient"
                LogMsg "Server ifconfig $(ip a)"
                SetTestStateFailed
                exit 0
            fi
        fi
    done
    CLIENT_NIC_IPs=$(ssh root@"$VF_IP2" "ip add show | grep -v SLAVE | grep BROADCAST | sed 's/:/ /g' | awk '{print \$2}'")
    for CLIENT_NIC in "${CLIENT_NIC_IPs[@]}"
    do
        client_ip_address=$(ssh root@"$VF_IP2" "ip addr show $CLIENT_NIC | grep 'inet\b'")
        if [[ -z "$client_ip_address" ]] ; then
            ssh root@"${VF_IP2}" "pkill dhclient"
            sleep 1
            ssh root@"${VF_IP2}" "timeout 10 dhclient $CLIENT_NIC"
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

# Install iPerf3
ssh -i "$HOME"/.ssh/"$SSH_PRIVATE_KEY" -o StrictHostKeyChecking=no "$remote_user"@"$VF_IP2" ". /home/${SUDO_USER}/utils.sh && update_repos && install_iperf3 && stop_firewall"
if [ $? -ne 0 ]; then
    LogErr "Could not install iPerf3 on VM2 (VF_IP: ${VF_IP2})"
    SetTestStateFailed
    exit 0
fi

update_repos
install_iperf3
stop_firewall
# Start iPerf server on dependency VM
LogMsg "Start iPerf server on VM $VF_IP2."
ssh -i "$HOME"/.ssh/"$SSH_PRIVATE_KEY" -o StrictHostKeyChecking=no "$remote_user"@"$VF_IP2" 'iperf3 -s -D > perfResults.log'
if [ $? -ne 0 ]; then
    LogErr "Could not start iPerf3 on VM2 (VF_IP: ${VF_IP2})"
    SetTestStateFailed
    exit 0
fi

# Start iPerf client and the time=1800 just make sure the traffic keep running during the whole test
LogMsg "Start iPerf client locally."
iperf3 -t 1800 -c "${VF_IP2}" --logfile perfResults.log &
if [ $? -ne 0 ]; then
    LogErr "Could not start iPerf3 on VM1 (VF_IP: ${VF_IP1})"
    SetTestStateFailed
    exit 0
fi

sleep 10
iperf_errors=$(cat perfResults.log | grep -i error)
if [ $? -eq 0 ]; then
    LogErr "iPerf3 had errors while running"
    LogErr "$iperf_errors"
    SetTestStateFailed
    exit 0
fi

# Check if the VF count inside the VM is the same as the expected count
vf_count=$(find /sys/devices -name net -a -ipath '*vmbus*' | grep pci | wc -l)
if [ "$vf_count" -ne "$NIC_COUNT" ]; then
    LogErr "Expected VF count: $NIC_COUNT. Actual VF count: $vf_count"
    SetTestStateFailed
    exit 0
fi
UpdateSummary "Expected VF count: $NIC_COUNT. Actual VF count: $vf_count"

declare -A offload_features_default_status
offload_features_default_status=([tcp-segmentation-offload]="" [scatter-gather]="" [generic-segmentation-offload]="" [generic-receive-offload]="" [large-receive-offload]="" [rx-vlan-offload]="" [tx-vlan-offload]="" [rx-checksumming]="" [tx-checksumming]="")

__iterator=1
__ip_iterator_1=1
__ip_iterator_2=2

# Check all the interfaces with VF
while [ $__iterator -le "$vf_count" ]; do
    # Extract VF_IP values
    ip_variable_name="VF_IP$__ip_iterator_1"
    static_IP_1="${!ip_variable_name}"
    ip_variable_name="VF_IP$__ip_iterator_2"
    static_IP_2="${!ip_variable_name}"

    synthetic_interface_vm_1=$(ip addr | grep $static_IP_1 | awk '{print $NF}')
    LogMsg  "Synthetic interface found: $synthetic_interface_vm_1"
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
    LogMsg "Virtual function found: $vf_interface_vm_1"

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

    # Get default status of features
    for key in ${!offload_features_default_status[*]}
    do
        status=$(ethtool -k $synthetic_interface_vm_1 2>&1 | grep "^$key" | head -n 1 | awk {'print $2'})
        if [ ${status} != "on" ] && [ ${status} != "off" ]; then
            LogErr "The status of $key is $status, but on or off is expected"
            SetTestStateFailed
            exit 0
        fi
        offload_features_default_status[$key]=$status
        LogMsg "The default status of $key:$status"
    done

    # Disable/enable SRIOV
    if ! DisableEnablePCI "SR-IOV"; then
        LogErr "Could not disable and reenable PCI device."
        SetTestStateFailed
        exit 0
    fi

    # Get status again after disable/enable SRIOV
    for key in ${!offload_features_default_status[*]}
    do
        status=$(ethtool -k $synthetic_interface_vm_1 2>&1 | grep "^$key" | head -n 1 | awk {'print $2'})
        if [ ${status} != "on" ] && [ ${status} != "off" ]; then
            LogErr "The status of $key is $status, but on or off is expected"
            SetTestStateFailed
            exit 0
        fi
        if [ ${status} != ${offload_features_default_status[$key]} ]; then
            LogErr "The status of $key is changed from ${offload_features_default_status[$key]} to $status after disable/enable SRIOV"
            SetTestStateFailed
            exit 0
        fi
    done

    synthetic_interface_vm_1=$(ip addr | grep $static_IP_1 | awk '{print $NF}')
    LogMsg  "Synthetic interface found: $synthetic_interface_vm_1"
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
    LogMsg "Virtual function found: $vf_interface_vm_1"

    # The below is against scatter-gather feature
    # Step 1: Set the status of scatter-gather on and check it
    feature_name="scatter-gather"
    feature_device_name="sg"
    LogMsg "1. Set $synthetic_interface_vm_1 feature $feature_device_name to on"
    set_feature_status $synthetic_interface_vm_1 $feature_device_name "on"
    LogMsg "Verifying $synthetic_interface_vm_1 feature $feature_name is on"
    check_feature_status $synthetic_interface_vm_1 $feature_name "on"

    # Step 2: Check sync offloading features to VF NIC
    LogMsg "2. Verifying $vf_interface_vm_1 $feature_name on"
    check_feature_status $vf_interface_vm_1 $feature_name "on"

    synthetic_interface_vm_1=$(ip addr | grep $static_IP_1 | awk '{print $NF}')
    LogMsg  "Synthetic interface found: $synthetic_interface_vm_1"
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
    LogMsg "Virtual function found: $vf_interface_vm_1"

    # Step 3: Check scatter-gather feature to be tunable
    LogMsg "3. Set $synthetic_interface_vm_1 feature $feature_device_name to off"
    set_feature_status $synthetic_interface_vm_1 $feature_device_name "off"
    # Check sync offloading features to VF NIC again
    LogMsg "Verifying $vf_interface_vm_1 feature $feature_name is off"
    check_feature_status $vf_interface_vm_1 $feature_name "off"

    # Step 4: Disable/enable SRIOV
    LogMsg "4. Disable and enable back SR-IOV"
    if ! DisableEnablePCI "SR-IOV"; then
        LogErr "Could not disable and enable back PCI device."
        SetTestStateFailed
        exit 0
    fi

    synthetic_interface_vm_1=$(ip addr | grep $static_IP_1 | awk '{print $NF}')
    LogMsg  "Synthetic interface found: $synthetic_interface_vm_1"
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
    LogMsg "Virtual function found: $vf_interface_vm_1"

    # Step 5: Verify the changed setting persists on VF
    LogMsg "5. Verifying $synthetic_interface_vm_1 feature $feature_name is off"
    check_feature_status $synthetic_interface_vm_1 $feature_name "off"
    LogMsg "Verifying $vf_interface_vm_1 feature $feature_name is off"
    check_feature_status $vf_interface_vm_1 $feature_name "off"

    # It's expected that the perf is running during the whole test
    ps aux | grep iperf3 | grep -v grep
    if [ $? -ne 0 ]; then
        LogErr "The iperf3 is not running."
        SetTestStateFailed
        exit 0
    else
        LogMsg "Verified iperf3 is still running successfully"
    fi

    __ip_iterator_1=$(($__ip_iterator_1 + 2))
    __ip_iterator_2=$(($__ip_iterator_2 + 2))
    : $((__iterator++))
done

LogMsg "Updating test case state to completed"
SetTestStateCompleted
exit 0