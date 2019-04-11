#!/bin/bash

# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

# Description:
#   This script checks that a legacy and a synthetic network adapter work together, without causing network issues to the VM.
#   If there are more than one synthetic/legacy interfaces, it is enough for just one (of each type) to successfully ping the remote server.
#   If the IP_IGNORE Parameter is given, the interface which owns that given address will not be able to take part in the test and will only be used to communicate with LIS
#
#   Steps:
#   1. Get legacy and synthetic network interfaces
#   2. Try to get DHCP addresses for each of them
#       2a. If no DHCP, try to set static IP
#   3. Try to ping REMOTE_SERVER from each interface
#
############################################################################
declare __iface_ignore

# Source utils.sh
. utils.sh || {
    echo "unable to source utils.sh!"
    echo "TestAborted" > state.txt
    exit 0
}

# Source constants file and initialize most common variables
UtilsInit
GetDistro

# Check for tulip driver. If it's not present, test will be skipped
grep "CONFIG_NET_TULIP=y\|CONFIG_TULIP=m" /boot/config-$(uname -r)
if [ $? -ne 0 ]; then
    LogMsg "Warn: Tulip driver is not configured. Test skipped"
    SetTestStateSkipped
    exit 0
fi

# Parameter provided in constants file
if [ "${SYNTH_STATIC_IP:-UNDEFINED}" = "UNDEFINED" ]; then
    LogMsg "The test parameter SYNTH_STATIC_IP is not defined in constants file"
else
    # Validate that $SYNTH_STATIC_IP is the correct format
    CheckIP "$SYNTH_STATIC_IP"
    if [ 0 -ne $? ]; then
        LogErr "Variable SYNTH_STATIC_IP: $SYNTH_STATIC_IP does not contain a valid IPv4 address"
        SetTestStateAborted
        exit 0
    fi
fi

# Parameter provided in constants file
if [ "${LEGACY_STATIC_IP:-UNDEFINED}" = "UNDEFINED" ]; then
    LogMsg "The test parameter LEGACY_STATIC_IP is not defined in constants file"
else
    # Validate that $LEGACY_STATIC_IP is the correct format
    CheckIP "$LEGACY_STATIC_IP"
    if [ 0 -ne $? ]; then
        LogErr "Variable LEGACY_STATIC_IP: $LEGACY_STATIC_IP does not contain a valid IPv4 address"
        SetTestStateAborted
        exit 0
    fi
fi

IFS=',' read -a networkType <<< "$NIC_2"
if [[ ${networkType[0]} == Legacy* ]] && [ -d /sys/firmware/efi ]; then
    LogErr "Generation 2 VM does not support LegacyNetworkAdapter, skip test"
    SetTestStateAborted
    exit 0
fi

# Parameter provided in constants file
if [ "${SYNTH_NETMASK:-UNDEFINED}" = "UNDEFINED" ]; then
    LogMsg "The test parameter SYNTH_NETMASK is not defined in constants file . Defaulting to 255.255.255.0"
    SYNTH_NETMASK=255.255.255.0
fi

# Parameter provided in constants file
if [ "${LEGACY_NETMASK:-UNDEFINED}" = "UNDEFINED" ]; then
    LogMsg "The test parameter LEGACY_NETMASK is not defined in constants file . Defaulting to 255.255.255.0"
    LEGACY_NETMASK=255.255.255.0
fi

# Parameter provided in constants file
if [ "${REMOTE_SERVER:-UNDEFINED}" = "UNDEFINED" ]; then
    LogErr "The mandatory test parameter REMOTE_SERVER is not defined in constants file!"
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

    # Get the interface associated with the given IP_IGNORE
    __iface_ignore=$(ip -o addr show| grep "$ipv4" | cut -d ' ' -f2)
fi

if [ "${DISABLE_NM:-UNDEFINED}" = "UNDEFINED" ]; then
    LogMsg "The test parameter DISABLE_NM is not defined in constants file. If the NetworkManager is running it could interfere with the test."
else
    if [[ "$DISABLE_NM" =~ [Yy][Ee][Ss] ]]; then
        # work-around for suse where the network gets restarted in order to shutdown networkmanager.
        declare __orig_netmask
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

declare __lo_ignore
if [ "${LO_IGNORE:-UNDEFINED}" = "UNDEFINED" ]; then
    LogMsg "The test parameter LO_IGNORE is not defined in constants file! The loopback interface may be used during the test."
    __lo_ignore=''
else
    ip link show lo >/dev/null 2>&1
    if [ 0 -ne $? ]; then
        LogMsg "The loopback interface is not working"
    else
        __lo_ignore=lo
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

# Test interface
declare -i __synth_iterator
declare -ai __invalid_positions
for __synth_iterator in "${!SYNTH_NET_INTERFACES[@]}"; do
    ip link show "${SYNTH_NET_INTERFACES[$__synth_iterator]}" >/dev/null 2>&1
    if [ 0 -ne $? ]; then
        __invalid_positions=("${__invalid_positions[@]}" "$__synth_iterator")
        LogMsg "Warning synthetic interface ${SYNTH_NET_INTERFACES[$__synth_iterator]} is unusable"
    fi
done

if [ ${#SYNTH_NET_INTERFACES[@]} -eq  ${#__invalid_positions[@]} ]; then
    LogErr "No usable synthetic interface remains"
    SetTestStateFailed
    exit 0
fi

# reset iterator and remove invalid positions from array
__synth_iterator=0
while [ $__synth_iterator -lt ${#__invalid_positions[@]} ]; do
    # eliminate from SYNTH_NET_INTERFACES array the interface located on position ${__invalid_positions[$__synth_iterator]}
    SYNTH_NET_INTERFACES=("${SYNTH_NET_INTERFACES[@]:0:${__invalid_positions[$__synth_iterator]}}" "${SYNTH_NET_INTERFACES[@]:$((${__invalid_positions[$__synth_iterator]}+1))}")
    : $((__synth_iterator++))
done
unset __invalid_positions

if [ 0 -eq ${#SYNTH_NET_INTERFACES[@]} ]; then
    LogErr "This should not have happened. Probable internal error above line $LINENO"
    SetTestStateFailed
    exit 0
fi

# Get the legacy netadapter interface
GetLegacyNetInterfaces
if [ 0 -ne $? ]; then
    LogErr "No legacy network interfaces found"
    SetTestStateFailed
    exit 0
fi

# Remove loopback interface if LO_IGNORE is set
LEGACY_NET_INTERFACES=(${LEGACY_NET_INTERFACES[@]/$__lo_ignore/})
if [ ${#LEGACY_NET_INTERFACES[@]} -eq 0 ]; then
    LogErr "The only legacy interface is the loopback interface lo, which was set to be ignored."
    SetTestStateAborted
    exit 0
fi

# Remove interface if present
LEGACY_NET_INTERFACES=(${LEGACY_NET_INTERFACES[@]/$__iface_ignore/})
if [ ${#LEGACY_NET_INTERFACES[@]} -eq 0 ]; then
    LogErr "The only legacy interface is the one which LIS uses to send files/commands to the VM."
    SetTestStateAborted
    exit 0
fi
LogMsg "Found ${#LEGACY_NET_INTERFACES[@]} legacy interface(s): ${LEGACY_NET_INTERFACES[*]} in VM"

# Test interface
declare -i __legacy_iterator
declare -ai __invalid_positions
for __legacy_iterator in "${!LEGACY_NET_INTERFACES[@]}"; do
    ip link show "${LEGACY_NET_INTERFACES[$__legacy_iterator]}" >/dev/null 2>&1
    if [ 0 -ne $? ]; then
        # add current position to __invalid_positions array
        __invalid_positions=("${__invalid_positions[@]}" "$__legacy_iterator")
        LogMsg "Warning legacy interface ${LEGACY_NET_INTERFACES[$__legacy_iterator]} is unusable"
    fi
done

if [ ${#LEGACY_NET_INTERFACES[@]} -eq  ${#__invalid_positions[@]} ]; then
    LogErr "No usable legacy interface remains"
    SetTestStateFailed
    exit 0
fi

# reset iterator and remove invalid positions from array
__legacy_iterator=0
while [ $__legacy_iterator -lt ${#__invalid_positions[@]} ]; do
    LEGACY_NET_INTERFACES=("${LEGACY_NET_INTERFACES[@]:0:${__invalid_positions[$__legacy_iterator]}}" "${LEGACY_NET_INTERFACES[@]:$((${__invalid_positions[$__legacy_iterator]}+1))}")
    : $((__legacy_iterator++))
done
unset __invalid_positions

if [ 0 -eq ${#LEGACY_NET_INTERFACES[@]} ]; then
    LogErr "This should not have happened. Probable internal error above line $LINENO"
    SetTestStateFailed
    exit 0
fi

# Try to get DHCP address for synthetic adaptor and ping if configured
__synth_iterator=0
while [ $__synth_iterator -lt ${#SYNTH_NET_INTERFACES[@]} ]; do
    LogMsg "Trying to get an IP Address via DHCP on synthetic interface ${SYNTH_NET_INTERFACES[$__synth_iterator]}"
    CreateIfupConfigFile "${SYNTH_NET_INTERFACES[$__iterator]}" "dhcp"
    if [ 0 -eq $? ]; then
        if [ -n "$GATEWAY" ]; then
            LogMsg "Setting $GATEWAY as default gateway on dev ${SYNTH_NET_INTERFACES[$__synth_iterator]}"
            CreateDefaultGateway "$GATEWAY" "${SYNTH_NET_INTERFACES[$__synth_iterator]}"
            if [ 0 -ne $? ]; then
                LogMsg "Warning! Failed to set default gateway!"
            fi
        fi

        LogMsg "Trying to ping $REMOTE_SERVER from synthetic interface ${SYNTH_NET_INTERFACES[$__synth_iterator]}"
        # In some cases eth1 and eth2 would fail to ping6, restarting the network solves the issue
        if [ "$pingVersion" == "ping6" ] && [ ${#SYNTH_NET_INTERFACES[@]} -ge 1 ]; then
            if [[ "$DISTRO" == "redhat"* || "$DISTRO" == "centos"* ]]; then
                service network restart
                if [ $? -ne 0 ]; then
                    LogMsg "Unable to restart network service."
                fi
            fi
        fi

        # ping the remote host using an easily distinguishable pattern 0xcafed00d`null`syn`null`dhcp`null`
        "$pingVersion" -I "${SYNTH_NET_INTERFACES[$__synth_iterator]}" -c 10 -p "cafed00d0073796e006468637000" "$REMOTE_SERVER" >/dev/null 2>&1
        if [ 0 -eq $? ]; then
            # ping worked! Do not test any other interface
            LogMsg "Successfully pinged $REMOTE_SERVER through synthetic ${SYNTH_NET_INTERFACES[$__synth_iterator]} (dhcp)."
            break
        else
            LogMsg "Unable to ping $REMOTE_SERVER through synthetic ${SYNTH_NET_INTERFACES[$__synth_iterator]}"
        fi
    fi
    # shut interface down
    ip link set ${SYNTH_NET_INTERFACES[$__synth_iterator]} down
    LogMsg "Unable to get address from dhcp server on synthetic interface ${SYNTH_NET_INTERFACES[$__synth_iterator]}"
    : $((__synth_iterator++))
done

# If all dhcp requests or ping failed, try to set static ip.
if [ ${#SYNTH_NET_INTERFACES[@]} -eq $__synth_iterator ]; then
    if [ -z "$SYNTH_STATIC_IP" ]; then
        LogErr "No static IP Address provided for synthetic interfaces. DHCP failed. Unable to continue..."
        SetTestStateFailed
        exit 0
    else
        # reset iterator
        __synth_iterator=0
        while [ $__synth_iterator -lt ${#SYNTH_NET_INTERFACES[@]} ]; do
            SetIPstatic "$SYNTH_STATIC_IP" "${SYNTH_NET_INTERFACES[$__synth_iterator]}" "$SYNTH_NETMASK"
            LogMsg "$(ip -o addr show ${SYNTH_NET_INTERFACES[$__synth_iterator]} | grep -vi inet6)"
            if [ -n "$GATEWAY" ]; then
                LogMsg "Setting $GATEWAY as default gateway on dev ${SYNTH_NET_INTERFACES[$__synth_iterator]}"
                CreateDefaultGateway "$GATEWAY" "${SYNTH_NET_INTERFACES[$__synth_iterator]}"
                if [ 0 -ne $? ]; then
                    LogMsg "Warning! Failed to set default gateway!"
                fi
            fi

            # In some cases eth1 and eth2 would fail to ping6, restarting the network solves the issue
            if [ "$pingVersion" == "ping6" ] && [ ${#SYNTH_NET_INTERFACES[@]} -ge 1 ]; then
                if [[ "$DISTRO" == "redhat"* || "$DISTRO" == "centos"* ]]; then
                    service network restart
                    if [ $? -ne 0 ]; then
                        LogMsg "Unable to restart network service."
                    fi
                fi
            fi

            LogMsg "Trying to ping $REMOTE_SERVER"
            # ping the remote host using an easily distinguishable pattern 0xcafed00d`null`syn`null`static`null`
            "$pingVersion" -I "${SYNTH_NET_INTERFACES[$__synth_iterator]}" -c 10 -p "cafed00d0073796e0073746174696300" "$REMOTE_SERVER" >/dev/null 2>&1
            if [ 0 -eq $? ]; then
                # ping worked! Remove working element from __invalid_positions list
                LogMsg "Successfully pinged $REMOTE_SERVER through synthetic ${SYNTH_NET_INTERFACES[$__synth_iterator]} (static)."
                break
            else
                LogMsg "Unable to ping $REMOTE_SERVER through synthetic ${SYNTH_NET_INTERFACES[$__synth_iterator]}"
            fi
            : $((__synth_iterator++))
        done

        if [ ${#SYNTH_NET_INTERFACES[@]} -eq $__synth_iterator ]; then
            LogErr "Unable to set neither static address for synthetic interface(s) ${SYNTH_NET_INTERFACES[@]}"
            SetTestStateFailed
            exit 0
        fi
    fi
fi

# Try to get DHCP address for legacy adaptor
__legacy_iterator=0
while [ $__legacy_iterator -lt ${#LEGACY_NET_INTERFACES[@]} ]; do
    LogMsg "Trying to get an IP Address via DHCP on legacy interface ${LEGACY_NET_INTERFACES[$__legacy_iterator]}"
    CreateIfupConfigFile "${LEGACY_NET_INTERFACES[$__legacy_iterator]}" "dhcp"
    if [ 0 -eq $? ]; then
        if [ -n "$GATEWAY" ]; then
            LogMsg "Setting $GATEWAY as default gateway on dev ${LEGACY_NET_INTERFACES[$__legacy_iterator]}"
            CreateDefaultGateway "$GATEWAY" "${LEGACY_NET_INTERFACES[$__legacy_iterator]}"
            if [ 0 -ne $? ]; then
                LogMsg "Warning! Failed to set default gateway!"
            fi
        fi

        LogMsg "Trying to ping $REMOTE_SERVER from legacy interface ${LEGACY_NET_INTERFACES[$__legacy_iterator]}"
        # In some cases eth1 and eth2 would fail to ping6, restarting the network solves the issue
        if [ "$pingVersion" == "ping6" ] && [ ${#SYNTH_NET_INTERFACES[@]} -ge 1 ]; then
            if [[ "$DISTRO" == "redhat"* || "$DISTRO" == "centos"* ]]; then
                service network restart
                if [ $? -ne 0 ]; then
                    msg="Unable to restart network service."
                    LogMsg "$msg"
                    UpdateSummary "$msg"
                fi
            fi
        fi

        # ping the remote host using an easily distinguishable pattern 0xcafed00d`null`leg`null`dhcp`null`
        "$pingVersion" -I "${LEGACY_NET_INTERFACES[$__legacy_iterator]}" -c 10 -p "cafed00d006c6567006468637000" "$REMOTE_SERVER" >/dev/null 2>&1
        if [ 0 -eq $? ]; then
            # ping worked
            LogMsg "Successfully pinged $REMOTE_SERVER through legacy ${LEGACY_NET_INTERFACES[$__legacy_iterator]} (dhcp)."
            break
        else
            LogMsg "Unable to ping $REMOTE_SERVER through legacy ${LEGACY_NET_INTERFACES[$__legacy_iterator]}"
        fi
    fi
    # shut interface down
    ip link set ${LEGACY_NET_INTERFACES[$__legacy_iterator]} down
    LogMsg "Unable to get address from dhcp server on legacy interface ${LEGACY_NET_INTERFACES[$__legacy_iterator]}"
    : $((__legacy_iterator++))
done

# If dhcp failed, try to set static ip
if [ ${#LEGACY_NET_INTERFACES[@]} -eq $__legacy_iterator ]; then
    LogMsg "Unable to get address for legacy interface(s) ${LEGACY_NET_INTERFACES[@]} through DHCP"
    if [ -z "$LEGACY_STATIC_IP" ]; then
        LogErr "No static IP Address provided for legacy interfaces. DHCP failed. Unable to continue..."
        SetTestStateFailed
        exit 0
    else
        # reset iterator
        __legacy_iterator=0
        while [ $__legacy_iterator -lt ${#LEGACY_NET_INTERFACES[@]} ]; do
            SetIPstatic "$LEGACY_STATIC_IP" "${LEGACY_NET_INTERFACES[$__legacy_iterator]}" "$LEGACY_NETMASK"
            LogMsg "$(ip -o addr show ${LEGACY_NET_INTERFACES[$__legacy_iterator]} | grep -vi inet6)"
            if [ -n "$GATEWAY" ]; then
                LogMsg "Setting $GATEWAY as default gateway on dev ${LEGACY_NET_INTERFACES[$__legacy_iterator]}"
                CreateDefaultGateway "$GATEWAY" "${LEGACY_NET_INTERFACES[$__legacy_iterator]}"
                if [ 0 -ne $? ]; then
                    LogMsg "Warning! Failed to set default gateway!"
                fi
            fi

            LogMsg "Trying to ping $REMOTE_SERVER through legacy ${LEGACY_NET_INTERFACES[$__legacy_iterator]}"
            # ping the remote host using an easily distinguishable pattern 0xcafed00d`null`leg`null`static`null`
            "$pingVersion" -I "${LEGACY_NET_INTERFACES[$__legacy_iterator]}" -c 10 -p "cafed00d006c65670073746174696300" "$REMOTE_SERVER" >/dev/null 2>&1
            if [ 0 -eq $? ]; then
                LogMsg "Successfully pinged $REMOTE_SERVER through legacy ${LEGACY_NET_INTERFACES[$__legacy_iterator]} (static)."
                break
            else
                LogMsg "Unable to ping $REMOTE_SERVER through legacy ${LEGACY_NET_INTERFACES[$__legacy_iterator]}"
            fi
            : $((__legacy_iterator++))
        done

        if [ ${#LEGACY_NET_INTERFACES[@]} -eq $__legacy_iterator ]; then
            LogErr "Unable to set neither static address for legacy interface(s) ${LEGACY_NET_INTERFACES[@]}"
            SetTestStateFailed
            exit 0
        fi
    fi
fi

SetTestStateCompleted
exit 0