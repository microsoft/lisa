#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

# Source utils.sh
. utils.sh || {
    echo "unable to source utils.sh!"
    exit 0
}
UtilsInit

function Check_Gateway
{
    # Get interfaces that have default gateway set
    gw_interf=($(route -n | grep 'UG[ \t]' | awk '{print $8}'))

    for if_gw in ${gw_interf[@]}; do
        if [[ ${if_gw} == ${1} ]]; then
            return 0
        fi
    done

    return 1
}

function Configure_HV_Interfaces
{
    # Handle test variables
    let EXPECTED_INTERFACES_NO=1
    if [ ! -z "${HV_SYNTHETIC_NICS+x}" ]; then
        let EXPECTED_INTERFACES_NO=$EXPECTED_INTERFACES_NO+$HV_SYNTHETIC_NICS
    fi

    if [ ! -z "${HV_LEGACY_NICS+x}" ]; then
        grep "CONFIG_NET_TULIP=y\|CONFIG_TULIP=m" /boot/config-$(uname -r)
        if [ $? -ne 0 ]; then
            LogErr "Tulip driver is not configured. Test skipped"
            SetTestStateSkipped
            exit 0
        fi
        let EXPECTED_INTERFACES_NO=$EXPECTED_INTERFACES_NO+$HV_LEGACY_NICS
    fi

    # Check how many interfaces are visible to the VM
    if [ ${#IFACES[@]} -ne ${EXPECTED_INTERFACES_NO} ]; then
        LogErr "Test expected ${EXPECTED_INTERFACES_NO} interfaces to be visible on VM. Found ${#IFACES[@]} interfaces"
        SetTestStateFailed
        exit 0
    fi

    # Bring interfaces up, using dhcp
    for IFACE in ${IFACES[@]}; do
        if [ $IFACE == "eth0" ]; then
            continue
        fi

        # Get the specific nic name as seen by the VM
        LogMsg "Configuring interface ${IFACE}"
        CreateIfupConfigFile $IFACE dhcp
        if [ $? -ne 0 ]; then
            LogErr "Unable to create ifcfg-file for $IFACE"
            SetTestStateAborted
            return 1
        fi

        dhclient $IFACE
        # sleep to allow the interface to get configured
        sleep 3

        ip_address=$(ip addr show $IFACE | grep "inet\b" | grep -v '127.0.0.1' | awk '{print $2}' | cut -d/ -f1)
        if [[ ! -z "$ip_address" ]]; then
            LogMsg "Successfully set IP address ${ip_address} on interface ${IFACE}"
        fi

        # Chech for gateway
        LogMsg "Checking if default gateway is set for ${IFACE}"
        Check_Gateway $IFACE
        if [ $? -ne 0 ];  then
            route add -net 0.0.0.0 gw ${DEFAULT_GATEWAY} netmask 0.0.0.0 dev ${IFACE}
            if [ $? -ne 0 ]; then
                LogErr "Unable to set ${DEFAULT_GATEWAY} as Default Gateway for $IFACE"
                SetTestStateFailed
                exit 0
            fi
        fi
    done

    # Check if all interfaces have a default gateway
    GATEWAY_IF=($(route -n | grep 'UG[ \t]' | awk '{print $8}'))
    LogMsg "Gateway setup for each NIC - ${GATEWAY_IF}"
    if [ ${#GATEWAY_IF[@]} -ne $EXPECTED_INTERFACES_NO ]; then
        LogMsg "Checking interfaces with missing gateway address"
        for IFACE in ${IFACES[@]}; do
            Check_Gateway $IFACE
            if [ $? -ne 0 ]; then
                LogMsg "WARNING : No gateway found for interface ${IFACE}. Adding gateway."
                route add -net 0.0.0.0 gw ${DEFAULT_GATEWAY} netmask 0.0.0.0 dev ${IFACE}
                if [ $? -ne 0 ]; then
                    LogErr "Unable to set default gateway - ${DEFAULT_GATEWAY} for ${IFACE}"
                    SetTestStateFailed
                    exit 0
                fi
            fi
        done
    fi
    return 0
}

function main() {
    test_issue=0

    # Construct array of interfaces
    DEFAULT_GATEWAY=($(route -n | grep 'UG[ \t]' | awk '{print $2}'))
    IFACES=($(ls /sys/class/net/))
    # Check for interfaces with longer names - enp0s10f
    # Delete other interfaces - lo, virbr
    let COUNTER=0
    for i in "${!IFACES[@]}"; do
        if echo "${IFACES[$i]}" | grep -q "lo\|virbr"; then
            unset IFACES[$i]
        fi
        if [[ ${IFACES[$i]} == "enp0s10f" ]]; then
            IFACES[$i]=${IFACES[$i]}${COUNTER}
            let COUNTER=COUNTER+1
        fi
        if [ -z "${HV_LEGACY_NICS+x}" ]; then
            if echo "${IFACES[$i]}" | grep -q "en"; then
                unset IFACES[$i]
            fi
        fi
    done
    LogMsg "Array of NICs - ${IFACES[*]}"

    # If platform.txt is present, then the test is performed on Hyper-V
    if [ -e platform.txt ]; then
        Configure_HV_Interfaces
        if [ $? -ne 0 ]; then
            LogErr "Failed to configure Hyper-V NICs!"
            SetTestStateFailed
            exit 0
        fi
    fi

    # Check if every interface has an IP assigned
    for eth_name in ${IFACES[@]}; do
        eth_ip=$(ip a | grep $eth_name | sed -n '2 p' | awk '{print $2}')
        eth_name=eth8
        eth_number=$(echo $eth_name | sed 's/[^0-9]*//g')
        if [[ $eth_number -ge 8 ]]; then
            continue
        fi
        if [[ "${eth_ip}" != '' ]]; then
            UpdateSummary "IP for ${eth_name} is ${eth_ip}"
        else
            LogErr "IP for ${eth_name} is not set"
            eth_info=$(ip a | grep "${eth_name}" -A 2)
            LogErr "Additional info for ${eth_name}: ${eth_info}"
            test_issue=$(( test_issue + 1 ))
        fi
    done

    # Conclude the result
    if [[ "$test_issue" == "0" ]]; then
        SetTestStateCompleted
    else
        SetTestStateFailed
    fi
}

main
exit 0