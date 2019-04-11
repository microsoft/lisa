#!/bin/bash

# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

# Description:
#   This script tries to set each synthetic network interface to promiscuous and then ping the REMOTE_SERVER. Afterwards, it disables
#   the promiscuous mode again.
#
#   Steps:
#   1. Verify configuration file constants.sh
#   2. Determine synthetic interface(s)
#   3. Set static IPs on these interfaces
#       3a. If static IP is not configured, get address(es) via dhcp
#   4. Make sure synthetic interfaces are not in promiscuous mode and then set them to it
#   5. Ping REMOTE_SERVER
#   6. Disable promiscuous mode again
#
#############################################################################################################
# Source utils.sh
. utils.sh || {
    echo "unable to source utils.sh!"
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
            LogErr "Variable STATIC_IP: ${STATIC_IPS[$__iterator]} does not contain a valid IPv4 address "
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

if [ "${REMOTE_SERVER:-UNDEFINED}" = "UNDEFINED" ]; then
    LogMsg "The test parameter REMOTE_SERVER is not defined in constants file. No network connectivity test will be performed."
    SetTestStateAborted
    exit 0
fi

# Check for internet protocol version
CheckIPV6 "$REMOTE_SERVER"
if [[ $? -eq 0 ]]; then
    pingVersion="ping6"
else
    pingVersion="ping"
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

# Parameter provided in constants file
declare __iface_ignore
if [ "${ipv4:-UNDEFINED}" = "UNDEFINED" ]; then
    LogErr "The test parameter ipv4 is not defined in constants file! Make sure you are using the latest LIS code."
    SetTestStateFailed
    exit 0
else
    CheckIP "$ipv4"
    if [ 0 -ne $? ]; then
        LogErr "Test parameter ipv4 = $ipv4 is not a valid IP Address"
        SetTestStateFailed
        exit 0
    fi

    # Get the interface associated with the given ipv4
    __iface_ignore=$(ip -o addr show| grep "$ipv4" | cut -d ' ' -f2)
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
declare -i __iterator
for __iterator in "${!SYNTH_NET_INTERFACES[@]}"; do
    ip link show "${SYNTH_NET_INTERFACES[$__iterator]}" >/dev/null 2>&1
    if [ 0 -ne $? ]; then
        LogErr "Invalid synthetic interface ${SYNTH_NET_INTERFACES[$__iterator]}"
        SetTestStateFailed
        exit 0
    fi

    # make sure interface is not in promiscuous mode already
    ip link show "${SYNTH_NET_INTERFACES[$__iterator]}" | grep -i promisc
    if [ 0 -eq $? ]; then
        LogErr "Synthetic interface ${SYNTH_NET_INTERFACES[$__iterator]} is already in promiscuous mode"
        SetTestStateFailed
        exit 0
    fi
done

if [ ${#SYNTH_NET_INTERFACES[@]} -gt ${#STATIC_IPS[@]} ]; then
    LogMsg "No. of synthetic interfaces is greater than number of static IPs specified in constants file. Will use dhcp for ${SYNTH_NET_INTERFACES[@]:${#STATIC_IPS[@]}}"
fi

# set static ips
declare -i __iterator=0
for __iterator in ${!STATIC_IPS[@]} ; do
    # if number of static ips is greater than number of interfaces, just break.
    if [ "$__iterator" -ge "${#SYNTH_NET_INTERFACES[@]}" ]; then
        LogMsg "Number of static IP addresses in constants.sh is greater than number of concerned interfaces. All extra IP addresses are ignored."
        break
    fi

    # if failed to assigned address
    SetIPstatic "${STATIC_IPS[$__iterator]}" "${SYNTH_NET_INTERFACES[$__iterator]}" "$NETMASK"
    if [ 0 -ne $? ]; then
        LogErr "Failed to assign static ip ${STATIC_IPS[$__iterator]} netmask $NETMASK on interface ${SYNTH_NET_INTERFACES[$__iterator]}"
        SetTestStateFailed
        exit 0
    fi
    LogMsg "$(ip -o addr show ${SYNTH_NET_INTERFACES[$__iterator]} | grep -vi inet6)"
done

# set dhcp ips for remaining interfaces
__iterator=${#STATIC_IPS[@]}
while [ $__iterator -lt ${#SYNTH_NET_INTERFACES[@]} ]; do
    LogMsg "Trying to get an IP Address via DHCP on interface ${SYNTH_NET_INTERFACES[$__iterator]}"
    CreateIfupConfigFile "${SYNTH_NET_INTERFACES[$__iterator]}" "dhcp"
    if [ 0 -ne $? ]; then
        LogErr "Unable to get address for ${SYNTH_NET_INTERFACES[$__iterator]} through DHCP"
        SetTestStateFailed
        exit 0
    fi
    LogMsg "$(ip -o addr show ${SYNTH_NET_INTERFACES[$__iterator]} | grep -vi inet6)"
    : $((__iterator++))

done
sleep 5

# reset iterator
__iterator=0
declare -i __message_count=0
for __iterator in ${!SYNTH_NET_INTERFACES[@]}; do
    LogMsg "Setting ${SYNTH_NET_INTERFACES[$__iterator]} to promisc mode"
    # set interfaces to promiscuous mode
    ip link set dev ${SYNTH_NET_INTERFACES[$__iterator]} promisc on
    # make sure it was set
    __message_count=$(dmesg | grep -i "device ${SYNTH_NET_INTERFACES[$__iterator]} entered promiscuous mode" | wc -l)
    if [ "$__message_count" -ne 1 ]; then
        LogErr "$__message_count messages were found in dmesg log concerning synthetic interface ${SYNTH_NET_INTERFACES[$__iterator]} entering promiscuous mode"
        SetTestStateFailed
        exit 0
    fi

    # now check ip for promisc
    ip link show ${SYNTH_NET_INTERFACES[$__iterator]} | grep -i promisc
    if [ 0 -ne $? ]; then
        LogErr "Interface ${SYNTH_NET_INTERFACES[$__iterator]} is not set to promiscuous mode according to ip. Dmesg however contained an entry stating that it did."
        SetTestStateFailed
        exit 0
    fi

    LogMsg "Successfully set ${SYNTH_NET_INTERFACES[$__iterator]} to promiscuous mode"
    if [ -n "$GATEWAY" ]; then
        LogMsg "Setting $GATEWAY as default gateway on dev ${SYNTH_NET_INTERFACES[$__iterator]}"
        CreateDefaultGateway "$GATEWAY" "${SYNTH_NET_INTERFACES[$__iterator]}"
        if [ 0 -ne $? ]; then
            LogMsg "Warning! Failed to set default gateway!"
        fi
    fi

    # ping the remote server
    LogMsg "Trying to ping $REMOTE_SERVER"
    "$pingVersion" -I ${SYNTH_NET_INTERFACES[$__iterator]} -c 10 "$REMOTE_SERVER"
    if [ 0 -ne $? ]; then
        LogErr "Failed to ping $REMOTE_SERVER on synthetic interface ${SYNTH_NET_INTERFACES[$__iterator]}"
        SetTestStateFailed
        exit 0
    fi
    LogMsg "Successfully pinged $REMOTE_SERVER on synthetic interface ${SYNTH_NET_INTERFACES[$__iterator]}"

    # disable promiscuous mode
    LogMsg "Disabling promisc mode on ${SYNTH_NET_INTERFACES[$__iterator]}"
    ip link set dev ${SYNTH_NET_INTERFACES[$__iterator]} promisc off
    __message_count=$(dmesg | grep -i "device ${SYNTH_NET_INTERFACES[$__iterator]} left promiscuous mode" | wc -l)
    if [ "$__message_count" -ne 1 ]; then
        LogErr "$__message_count messages were found in dmesg log concerning synthetic interface ${SYNTH_NET_INTERFACES[$__iterator]} leaving promiscuous mode"
        SetTestStateFailed
        exit 0
    fi

    # now check ip for promisc
    ip link show ${SYNTH_NET_INTERFACES[$__iterator]} | grep -i promisc
    if [ 0 -eq $? ]; then
        LogErr "Interface ${SYNTH_NET_INTERFACES[$__iterator]} is set to promiscuous mode according to ip. Dmesg however contained an entry stating that it left that mode."
        SetTestStateFailed
        exit 0
    fi
    LogMsg "Successfully disabled promiscuous mode on ${SYNTH_NET_INTERFACES[$__iterator]}"
done

SetTestStateCompleted
exit 0