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
        LogMsg "Info : Configuring interface ${IFACE}"
        CreateIfupConfigFile $IFACE dhcp
        if [ $? -eq 0 ]; then
            ip_address=$(ip addr show $IFACE | grep "inet\b" | grep -v '127.0.0.1' | awk '{print $2}' | cut -d/ -f1)
            LogMsg "Info : Successfully set IP address - ${ip_address}"
        else
            LogErr "Error: Unable to create ifcfg-file for $IFACE"
            SetTestStateAborted
            return 1
        fi

        ifdown $IFACE && ifup $IFACE
        #sleep a while after ifup
        sleep 10
        # Chech for gateway
        LogMsg "Info : Checking if default gateway is set for ${IFACE}"
        Check_Gateway $IFACE
        if [ $? -ne 0 ];  then
            route add -net 0.0.0.0 gw ${DEFAULT_GATEWAY} netmask 0.0.0.0 dev ${IFACE}
            if [ $? -ne 0 ]; then
                LogErr "Error: Unable to set ${DEFAULT_GATEWAY} as Default Gateway for $IFACE"
                return 1
            fi
        fi
    done
    return 0
}

# Source utils.sh
. utils.sh || {
    echo "Error: unable to source utils.sh!"
    exit 0
}
UtilsInit

if [ "${TEST_TYPE:-UNDEFINED}" = "UNDEFINED" ]; then
    LogMsg "Error : Parameter TEST_TYPE was not found"
    SetTestStateAborted
    exit 0
else
    IFS=',' read -a TYPE <<< "$TEST_TYPE"
fi

if [ "${SYNTHETIC_NICS:-UNDEFINED}" = "UNDEFINED" ] && [ "${LEGACY_NICS:-UNDEFINED}" = "UNDEFINED" ]; then
    LogErr "Error : Parameters SYNTHETIC_NICS or LEGACY_NICS were not found"
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
    let EXPECTED_INTERFACES_NO=$EXPECTED_INTERFACES_NO+$LEGACY_NICS
fi

GetOSVersion
DEFAULT_GATEWAY=($(route -n | grep 'UG[ \t]' | awk '{print $2}'))

IFACES=($(ifconfig -s -a | awk '{print $1}'))
# Delete first element from the list - iface
IFACES=("${IFACES[@]:1}")
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

LogMsg "Info : Array of NICs - ${IFACES}"
# Check how many interfaces are visible to the VM
if [ ${#IFACES[@]} -ne ${EXPECTED_INTERFACES_NO} ]; then
    LogErr "Error : Test expected ${EXPECTED_INTERFACES_NO} interfaces to be visible on VM. Found ${#IFACES[@]} interfaces"
    SetTestStateFailed
    exit 0
fi

# Bring interfaces up, using dhcp
LogMsg "Info : Bringing up interfaces using DHCP"
Configure_Interfaces
if [ $? -ne 0 ]; then
    SetTestStateFailed
    exit 0
fi

# Check if all interfaces have a default gateway
GATEWAY_IF=($(route -n | grep 'UG[ \t]' | awk '{print $8}'))
LogMsg "Info : Gateway setup for each NIC - ${GATEWAY_IF}"
if [ ${#GATEWAY_IF[@]} -ne $EXPECTED_INTERFACES_NO ]; then
    LogMsg "Info : Checking interfaces with missing gateway address"
    for IFACE in ${IFACES[@]}; do
        Check_Gateway $IFACE
        if [ $? -ne 0 ]; then
            LogMsg "WARNING : No gateway found for interface ${IFACE}. Adding gateway."
            route add -net 0.0.0.0 gw ${DEFAULT_GATEWAY} netmask 0.0.0.0 dev ${IFACE}
            if [ $? -ne 0 ]; then
                LogErr "Error : Unable to set default gateway - ${DEFAULT_GATEWAY} for ${IFACE}"
                SetTestStateFailed
                exit 0
            fi
        fi
    done
fi

SetTestStateCompleted
exit 0