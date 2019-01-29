#!/bin/bash

# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

#############################################################################################################
#
# Description:
#   This script tries to set the mtu of each synthetic network adapter to 65536 or whatever the maximum it accepts
#   and ping a second VM with large packet sizes. All synthetic interfaces need to have the same max MTU.
#   The STATIC_IP2 also needs to have its interface set to the high MTU.
#
#   Steps:
#   1. Verify configuration file constants.sh
#   2. Determine synthetic interface(s)
#   3. Set static IPs on these interfaces
#       3a. If static IP is not configured, get address(es) via dhcp
#   4. Set MTU to 65536 or the maximum that the interface accepts
#   5. If SSH_PRIVATE_KEY was passed, ssh into the STATIC_IP2 and set the MTU to the same value as above, on the interface
#       owning that IP Address
#   5. Ping STATIC_IP2
#
#   The test is successful if all synthetic interfaces were able to set the same maximum MTU and then
#   were able to ping the STATIC_IP2 with all various packet-sizes.
#
#############################################################################################################
remote_user=$(whoami)
. net_constants.sh || {
    echo "unable to source net_constants.sh!"
    echo "TestAborted" > state.txt
    exit 2
}
# Source utils.sh
. utils.sh || {
    echo "unable to source utils.sh!"
    echo "TestAborted" > state.txt
    exit 2
}
# Source constants file and initialize most common variables
UtilsInit

# Check and set parameters
if [ "${STATIC_IP:-UNDEFINED}" = "UNDEFINED" ]; then
    LogErr "The test parameter STATIC_IP is not defined in constants file"
    SetTestStateAborted
    exit 0
fi
if [ "${STATIC_IP2:-UNDEFINED}" = "UNDEFINED" ]; then
    LogErr "The test parameter STATIC_IP2 is not defined in constants file"
    SetTestStateAborted
    exit 0
fi
if [ "${NETMASK:-UNDEFINED}" = "UNDEFINED" ]; then
    msg="The test parameter NETMASK is not defined in constants file . Defaulting to 255.255.255.0"
    LogMsg "$msg"
    NETMASK=255.255.255.0
fi
if [ "$ADDRESS_FAMILY" = "ipv6" ];then 
    ping_version=ping6
else 
    ping_version=ping
fi

# Parameter provided in constants file
if [ "${ipv4:-UNDEFINED}" = "UNDEFINED" ]; then
    LogErr "The test parameter ipv4 is not defined in constants file"
    SetTestStateAborted
    exit 0
else
    # Get the interface associated with the given ipv4
    iface_ignore=$(ip -o addr show| grep "$ipv4" | cut -d ' ' -f2)
fi

# Retrieve synthetic network interfaces
GetSynthNetInterfaces
if [ 0 -ne $? ]; then
    LogErr "No synthetic network interfaces found"
    SetTestStateFailed
    exit 0
fi

# Remove interface if present
SYNTH_NET_INTERFACES=(${SYNTH_NET_INTERFACES[@]/$iface_ignore/})
if [ ${#SYNTH_NET_INTERFACES[@]} -eq 0 ]; then
    LogErr "The only synthetic interface is the one which LIS uses to send files/commands to the VM."
    SetTestStateAborted
    exit 0
fi
test_iface=${SYNTH_NET_INTERFACES[*]}
LogMsg "Found ${#SYNTH_NET_INTERFACES[@]} synthetic interface(s): $test_iface in VM"
ip link show $test_iface >/dev/null 2>&1
if [ 0 -ne $? ]; then
    LogErr "Invalid synthetic interface $test_iface"
    SetTestStateFailed
    exit 0
fi

# Set static ip
CreateIfupConfigFile "$test_iface" "static" "$STATIC_IP" "$NETMASK"
# if failed to assigned address
if [ 0 -ne $? ]; then
    LogErr "Failed to assign static ip $STATIC_IP netmask $NETMASK on interface $test_iface"
    SetTestStateFailed
    exit 0
fi
ip link show $test_iface $igno

# try to set mtu to 65536
# save the maximum capable mtu
change_mtu_increment $test_iface $iface_ignore
if [ $? -ne 0 ]; then
    LogErr "Failed to change MTU on $test_iface"
    SetTestStateFailed
    exit 0
fi

# Change MTU on dependency VM
if [ "${SSH_PRIVATE_KEY:-UNDEFINED}" != "UNDEFINED" ]; then
    LogMsg "Setting all interfaces on $STATIC_IP2 mtu to $max_mtu"
    ssh -i "$HOME"/.ssh/"$SSH_PRIVATE_KEY" -o StrictHostKeyChecking=no "$remote_user"@"$STATIC_IP2" "
        remote_interface=\$(ip -o addr show | grep \"$STATIC_IP2\" | cut -d ' ' -f2)
        if [ x\"\$remote_interface\" = x ]; then
            exit 1
        fi
        # make sure no legacy interfaces are present
        legacy_interface_no=\$(find /sys/devices -name net -a ! -ipath '*vmbus*' -a ! -path '*virtual*' -a ! -path '*lo*' | wc -l)

        if [ 0 -ne \"\$legacy_interface_no\" ]; then
            exit 2
        fi
        ip link set dev \$remote_interface mtu \"$max_mtu\"
        if [ 0 -ne \$? ]; then
            exit 2
        fi
        remote_actual_mtu=\$(ip -o link show \"\$remote_interface\" | cut -d ' ' -f5)
        if [ x\"\$remote_actual_mtu\" !=  x\"$max_mtu\" ]; then
            exit 3
        fi
        exit 0
        "
    if [ 0 -ne $? ]; then
        LogErr "Unable to set $STATIC_IP2 mtu to $max_mtu"
        SetTestStateFailed
        exit 0
    fi
else
    LogErr "SSH_PRIVATE_KEY param missing"
    SetTestStateAborted
    exit 0
fi
LogMsg "Successfully increased MTU up to $max_mtu on both VMs"

declare -ai packet_size=(0 1 2 48 64 512 1440 1500 1505 4096 4192 25152 61404)
# 20 bytes IP header + 8 bytes ICMP header
declare -i const_ping_header=28

for packet_iterator in ${!packet_size[@]}; do
    if [ ${packet_size[$packet_iterator]} -gt $((max_mtu-const_ping_header)) ]; then
        # reached the max packet size for our max mtu
        break
    fi
    hex_ping_value=$(echo -n "${packet_size[$packet_iterator]}" | od -A n -t x1 | sed 's/ //g' | cut -c1-10)
    LogMsg "Trying to ping $STATIC_IP2 from interface $test_iface with packet-size ${packet_size[$packet_iterator]}"
    "$ping_version" -I "$test_iface" -c 10 -p "cafed00d006a756d6200${hex_ping_value}00" -s "${packet_size[$packet_iterator]}" "$STATIC_IP2"
    if [ 0 -ne $? ]; then
        LogErr "Failed to ping $STATIC_IP2 through interface $test_iface with packet-size ${packet_size[$packet_iterator]}"
        SetTestStateFailed
        exit 0
    fi
    LogMsg "Successfully pinged!"
done

SetTestStateCompleted
exit 0