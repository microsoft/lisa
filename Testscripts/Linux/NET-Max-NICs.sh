#!/bin/bash

# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

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

function Configure_Interfaces
{
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
                return 1
            fi
        fi
    done
    return 0
}

# Source utils.sh
. utils.sh || {
    echo "unable to source utils.sh!"
    exit 0
}
UtilsInit

if [ "${TEST_TYPE:-UNDEFINED}" = "UNDEFINED" ]; then
    LogMsg "Parameter TEST_TYPE was not found, defaulting to Synthetic NICs"
    TEST_TYPE="synthetic"
fi

if [ "${SYNTHETIC_NICS:-UNDEFINED}" = "UNDEFINED" ] && [ "${LEGACY_NICS:-UNDEFINED}" = "UNDEFINED" ]; then
    LogErr "Parameters SYNTHETIC_NICS or LEGACY_NICS were not found"
    SetTestStateAborted
    exit 0
fi

let EXPECTED_INTERFACES_NO=1
if [ -z "${SYNTHETIC_NICS+x}" ]; then
    LogMsg "Parameter SYNTHETIC_NICS was not found"
else
    let EXPECTED_INTERFACES_NO=$EXPECTED_INTERFACES_NO+$SYNTHETIC_NICS
fi

if [ -z "${LEGACY_NICS+x}" ]; then
    LogMsg "Parameter LEGACY_NICS was not found"
else
    grep "CONFIG_NET_TULIP=y\|CONFIG_TULIP=m" /boot/config-$(uname -r)
    if [ $? -ne 0 ]; then
        LogErr "Tulip driver is not configured. Test skipped"
        SetTestStateSkipped
        exit 0
    fi
    let EXPECTED_INTERFACES_NO=$EXPECTED_INTERFACES_NO+$LEGACY_NICS
fi

GetOSVersion
DEFAULT_GATEWAY=($(route -n | grep 'UG[ \t]' | awk '{print $2}'))

IFACES=($(ls /sys/class/net/))
# Check for interfaces with longer names - enp0s10f
# Delete other interfaces - lo, virbr
let COUNTER=0
for i in "${!IFACES[@]}"; do
    if echo "${IFACES[$i]}" | grep -q "lo\|virbr"; then
        echo "Found"
        unset IFACES[$i]
    fi
    if [[ ${IFACES[$i]} == "enp0s10f" ]]; then
        IFACES[$i]=${IFACES[$i]}${COUNTER}
        let COUNTER=COUNTER+1
    fi
done

LogMsg "Array of NICs - ${IFACES}"
# Check how many interfaces are visible to the VM
if [ ${#IFACES[@]} -ne ${EXPECTED_INTERFACES_NO} ]; then
    LogErr "Test expected ${EXPECTED_INTERFACES_NO} interfaces to be visible on VM. Found ${#IFACES[@]} interfaces"
    SetTestStateFailed
    exit 0
fi

# Bring interfaces up, using dhcp
LogMsg "Bringing up interfaces using DHCP"
Configure_Interfaces
if [ $? -ne 0 ]; then
    SetTestStateFailed
    exit 0
fi

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

SetTestStateCompleted
exit 0
