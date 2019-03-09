#!/bin/bash

# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

# Description:
#    This script verifies that all synthetic interfaces can ping an IP
# Address and cannot ping at least one IP Address. Usually there is one
# ping-able address specified, that is on the same network as the interface(s)
# and two for the other two network adapter types, which should not be
# ping-able.
#
#    Steps:
#    1. Verify configuration file constants.sh
#    2. Determine synthetic network interfaces
#    3. Set static IPs on interfaces
#        3a. If static IP is not configured, get address(es) via dhcp
#    4. Ping IPs
#
###############################################################################
# Source utils.sh
. utils.sh || {
    echo "unable to source utils.sh!"
    echo "TestAborted" > state.txt
    exit 0
}
# Source net_constants.sh file
. net_constants.sh || {
    echo "unable to source net_constants.sh!"
    echo "TestAborted" > state.txt
    exit 0
}

# Source constants file and initialize most common variables
UtilsInit

# Parameter provided in constants file
declare -a STATIC_IPS=()
if [ "${STATIC_IP:-UNDEFINED}" = "UNDEFINED" ]; then
    LogMsg "The test parameter STATIC_IP is not defined in constants file. Will try to set addresses via dhcp"
else
    # Split (if necessary) IP Adddresses based on , (comma)
    IFS=',' read -a STATIC_IPS <<< "$STATIC_IP"
    declare -i __iterator

    # Validate that $STATIC_IP is the correct format
    for __iterator in ${!STATIC_IPS[@]}; do
        CheckIP "${STATIC_IPS[$__iterator]}"
        if [ 0 -ne $? ]; then
            LogMsg "Variable STATIC_IP: ${STATIC_IPS[$__iterator]} does not contain a valid IPv4 address"
            SetTestStateAborted
            exit 0
        fi
    done
    unset __iterator
fi

NIC=$(echo $NIC_{1..9})
IFS=',' read -a networkType <<< "$NIC"

if [ "${NETMASK:-UNDEFINED}" = "UNDEFINED" ]; then
    LogMsg "The test parameter NETMASK is not defined in constants file . Defaulting to 255.255.255.0"
    NETMASK=255.255.255.0
fi

if [ "${PING_SUCC:-UNDEFINED}" = "UNDEFINED" ]; then
    LogErr "The test parameter PING_SUCC is not defined in constants file"
    SetTestStateAborted
    exit 0
fi

if [ "${PING_FAIL:-UNDEFINED}" = "UNDEFINED" ]; then
    LogErr "The test parameter PING_FAIL is not defined in constants file"
    SetTestStateAborted
    exit 0
fi

#
# Check for internet protocol version
#
CheckIPV6 "$PING_SUCC"
if [[ $? -eq 0 ]]; then
    CheckIPV6 "$PING_FAIL"
    if [[ $? -eq 0 ]]; then
        pingVersion="ping6"
    else
        LogErr "Not both test IPs are IPV6"
        SetTestStateFailed
        exit 0
    fi
else
    pingVersion="ping"
fi

if [ "${PING_FAIL2:-UNDEFINED}" = "UNDEFINED" ]; then
    LogMsg "The test parameter PING_FAIL2 is not defined in constants file."
fi

# set gateway parameter
if [ "${GATEWAY:-UNDEFINED}" = "UNDEFINED" ]; then
    if [ "${networkType[2]}" = "External" ]; then
        LogMsg "The test parameter GATEWAY is not defined in constants file . The default gateway will be set for all interfaces."
        GATEWAY=$(/sbin/ip route | awk '/default/ { print $3 }')
    else
        LogMsg "The test parameter GATEWAY is not defined in constants file . No gateway will be set."
        GATEWAY=''
    fi
else
    CheckIP "$GATEWAY"
    if [ 0 -ne $? ]; then
        SetTestStateAborted
        exit 0
    fi
fi

declare __iface_ignore

# Parameter provided in constants file
#    ipv4 is the IP Address of the interface used to communicate with the VM, which needs to remain unchanged
#    it is not touched during this test (no dhcp or static ip assigned to it)

if [ "${ipv4:-UNDEFINED}" = "UNDEFINED" ]; then
    LogErr "The test parameter ipv4 is not defined in constants file! Make sure you are using the latest LIS code."
    SetTestStateAborted
    exit 0
else
    CheckIP "$ipv4"
    if [ 0 -ne $? ]; then
        LogErr "Test parameter ipv4 = $ipv4 is not a valid IP Address"
        SetTestStateAborted
        exit 0
    fi

    # Get the interface associated with the given ipv4
    __iface_ignore=$(ip -o addr show | grep "$ipv4" | cut -d ' ' -f2)
fi

if [ "${DISABLE_NM:-UNDEFINED}" = "UNDEFINED" ]; then
    LogMsg "The test parameter DISABLE_NM is not defined in constants file. If the NetworkManager is running it could interfere with the test."
else
    if [[ "$DISABLE_NM" =~ [Yy][Ee][Ss] ]]; then

        # work-around for suse where the network gets restarted in order to shutdown networkmanager.
        declare __orig_netmask
        GetDistro
        case "$DISTRO" in
            suse*)
                __orig_netmask=$(ip -o addr show | grep "$ipv4" | cut -d '/' -f2 | cut -d ' ' -f1)
                ;;
        esac
        DisableNetworkManager
        case "$DISTRO" in
            suse*)
                ip link set "$__iface_ignore" down
                ip addr flush dev "$__iface_ignore"
                ip addr add "$ipv4"/"$__orig_netmask" dev "$__iface_ignore"
                ip link set "$__iface_ignore" up
                ;;
        esac
    fi
fi

# Retrieve synthetic network interfaces
GetSynthNetInterfaces
if [ 0 -ne $? ]; then
    LogErr "No synthetic network interfaces found"
    SetTestStateFailed
    exit 0
fi

# Remove interface if present
SYNTH_NET_INTERFACES=(${SYNTH_NET_INTERFACES[@]/$__iface_ignore/})
if [ ${#SYNTH_NET_INTERFACES[@]} -eq 0 ]; then
    LogErr "The only synthetic interface is the one which LIS uses to send files/commands to the VM."
    SetTestStateAborted
    exit 0
fi
LogMsg "Found ${#SYNTH_NET_INTERFACES[@]} synthetic interface(s): ${SYNTH_NET_INTERFACES[*]} in VM"

# Test interfaces
# First, verify if an interface with a given MAC address exists on the VM
if [ "${MAC:-UNDEFINED}" != "UNDEFINED" ]; then
    grep -il "$MAC" /sys/class/net/*/address
    if [ 0 -ne $? ]; then
        LogErr "MAC Address $MAC does not belong to any interface."
        SetTestStateFailed
        exit 0
    else
        LogMsg "MAC Address $MAC was found on the VM"
    fi
fi

declare -i __iterator
for __iterator in "${!SYNTH_NET_INTERFACES[@]}"; do
    ip link show "${SYNTH_NET_INTERFACES[$__iterator]}" >/dev/null 2>&1
    if [ 0 -ne $? ]; then
        LogErr "Invalid synthetic interface ${SYNTH_NET_INTERFACES[$__iterator]}"
        SetTestStateFailed
        exit 0
    fi
done

if [ ${#SYNTH_NET_INTERFACES[@]} -gt ${#STATIC_IPS[@]} ]; then
    LogMsg "No. of synthetic interfaces is greater than number of static IPs specified in constants file. Will use dhcp for ${SYNTH_NET_INTERFACES[@]:${#STATIC_IPS[@]}}"
fi

declare -i __iterator=0

# set static ips
for __iterator in ${!STATIC_IPS[@]} ; do
    # if number of static ips is greater than number of interfaces, just break.
    if [ "$__iterator" -ge "${#SYNTH_NET_INTERFACES[@]}" ]; then
        LogMsg "Number of static IP addresses in constants.sh is greater than number of concerned interfaces. All extra IP addresses are ignored."
        break
    fi

    SetIPstatic "${STATIC_IPS[$__iterator]}" "${SYNTH_NET_INTERFACES[$__iterator]}" "$NETMASK"
    # if failed to assigned address
    if [ 0 -ne $? ]; then
        LogErr "Failed to assign static ip ${STATIC_IPS[$__iterator]} netmask $NETMASK on interface ${SYNTH_NET_INTERFACES[$__iterator]}"
        SetTestStateFailed
        exit 0
    fi

    LogMsg "Successfully assigned ${STATIC_IPS[$__iterator]} ($NETMASK) to synthetic interface ${SYNTH_NET_INTERFACES[$__iterator]}"
    # add some interface output
    LogMsg "$(ip -o addr show ${SYNTH_NET_INTERFACES[$__iterator]} | grep -vi inet6)"
done

# Set dhcp ips for remaining interfaces
# set the iterator to point to the next element in the SYNTH_NET_INTERFACES array
__iterator=${#STATIC_IPS[@]}
while [ $__iterator -lt ${#SYNTH_NET_INTERFACES[@]} ]; do
    LogMsg "Trying to get an IP Address via DHCP on interface ${SYNTH_NET_INTERFACES[$__iterator]}"
    CreateIfupConfigFile "${SYNTH_NET_INTERFACES[$__iterator]}" "dhcp"
    if [ 0 -ne $? ]; then
        LogErr "Unable to get address for ${SYNTH_NET_INTERFACES[$__iterator]} through DHCP"
        SetTestStateFailed
        exit 0
    fi
    # add some interface output
    LogMsg "$(ip -o addr show ${SYNTH_NET_INTERFACES[$__iterator]} | grep -vi inet6)"
    : $((__iterator++))
done

# Reset iterator
__iterator=0
declare __hex_interface_name
sleep 5
for __iterator in ${!SYNTH_NET_INTERFACES[@]}; do
    if [ -n "$GATEWAY" ]; then
        LogMsg "Setting $GATEWAY as default gateway on dev ${SYNTH_NET_INTERFACES[$__iterator]}"
        CreateDefaultGateway "$GATEWAY" "${SYNTH_NET_INTERFACES[$__iterator]}"
        if [ 0 -ne $? ]; then
            LogWarn "Failed to set default gateway!"
        fi
    fi

    # In some cases eth1 and eth2 would fail to ping6, restarting the network solves the issue
    if [ "$pingVersion" == "ping6" ] && [ ${#SYNTH_NET_INTERFACES[@]} -gt 1 ]; then
        GetDistro
        if [[ "$DISTRO" == "redhat"* || "$DISTRO" == "centos"* ]]; then
            service network restart
            sleep 5
            if [ $? -ne 0 ]; then
                LogMsg "Unable to restart network service."
            fi
        fi
    fi

    __hex_interface_name=$(echo -n "${__packet_size[$__packet_iterator]}" | od -A n -t x1 | sed 's/ //g' | cut -c1-12)

    LogMsg "Trying to ping $PING_SUCC on interface ${SYNTH_NET_INTERFACES[$__iterator]}"
    # ping the right address with pattern 0xcafed00d`null`test`null`dhcp`null`
    "$pingVersion" -I ${SYNTH_NET_INTERFACES[$__iterator]} -c 10 -p "cafed00d007465737400${__hex_interface_name}00" "$PING_SUCC"
    if [ 0 -ne $? ]; then
        LogErr "Failed to ping $PING_SUCC on synthetic interface ${SYNTH_NET_INTERFACES[$__iterator]}"
        SetTestStateFailed
        exit 0
    fi
    LogMsg "Successfully pinged $PING_SUCC on synthetic interface ${SYNTH_NET_INTERFACES[$__iterator]}"

    # ping the wrong address. should not succeed
    LogMsg "Trying to ping $PING_FAIL on interface ${SYNTH_NET_INTERFACES[$__iterator]}"
    "$pingVersion" -I ${SYNTH_NET_INTERFACES[$__iterator]} -c 10 "$PING_FAIL"
    if [ 0 -eq $? ]; then
        LogErr "Succeeded to ping $PING_FAIL on synthetic interface ${SYNTH_NET_INTERFACES[$__iterator]} . Make sure you have the right PING_FAIL constant set"
        SetTestStateFailed
        exit 0
    fi
    LogMsg "Failed to ping $PING_FAIL on synthetic interface ${SYNTH_NET_INTERFACES[$__iterator]} (as expected)"

    # ping the second wrong address, if specified
    if [ "${PING_FAIL2:-UNDEFINED}" != "UNDEFINED" ]; then
        LogMsg "Trying to ping $PING_FAIL on interface ${SYNTH_NET_INTERFACES[$__iterator]}"
        "$pingVersion" -I ${SYNTH_NET_INTERFACES[$__iterator]} -c 10 "$PING_FAIL2"
        if [ 0 -eq $? ]; then
            LogErr "Succeeded to ping $PING_FAIL2 on synthetic interface ${SYNTH_NET_INTERFACES[$__iterator]} . Make sure you have the right PING_FAIL2 constant set"
            SetTestStateFailed
            exit 0
        fi
        LogMsg "Failed to ping $PING_FAIL2 on synthetic interface ${SYNTH_NET_INTERFACES[$__iterator]} (as expected)"
    fi

done
CreateDefaultGateway "$GATEWAY" "$__iface_ignore"
SetTestStateCompleted
exit 0
