#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

#############################################################################
#
# Description:
#    This script will first check the existence of ethtool on vm and will
#    get the link settings and then reset it from ethtool.
#
#############################################################################
# Source utils.sh
. utils.sh || {
    echo "Error: unable to source utils.sh!"
    echo "TestAborted" > state.txt
    exit 0
}

# Source constants file and initialize most common variables
UtilsInit

#######################################################################
# Main script body
#######################################################################
# Check if ethtool exist and install it if not
VerifyIsEthtool

if ! GetSynthNetInterfaces; then
    LogErr "No synthetic network interfaces found"
    SetTestStateFailed
    exit 0
fi

net_interface=${SYNTH_NET_INTERFACES[0]}
LogMsg "The network interface is $net_interface"

# Get the information of the link
duplex=$(ethtool $net_interface | grep "Duplex" | tr ":" " " | awk '{print $NF}')
if [ $duplex != "Full" -a $duplex != "Half" ]; then
    LogErr "The duplex is $duplex, but Full or Half is expected"
    SetTestStateFailed
    exit 0
fi

speed=$(ethtool $net_interface | grep "Speed" | tr ":" " " | awk '{print $NF}')
if [ ! $speed ]; then
    LogErr "The speed is null!"
    SetTestStateFailed
    exit 0
fi

port=$(ethtool $net_interface | grep "Port" | tr ":" " " | awk '{print $NF}')

LogMsg "The link settings of $net_interface:"
LogMsg "    Duplex:$duplex"
LogMsg "    Speed:$speed"
LogMsg "    Port:$port"

LogMsg "Attempting to change $net_interface settings using ethtool"
autoneg=$(ethtool -s $net_interface autoneg off)
LogMsg "Ethtool output for attempt to change auto-negotiation to off:$autoneg"
duplex=$(ethtool -s $net_interface duplex half)
LogMsg "Ethtool output for attempt to change duplex to half-duplex:$duplex"
speed=$(ethtool -s $net_interface speed 100)
LogMsg "Ethtool output for attempt to change speed to 100Mb/s:$speed"

SetTestStateCompleted
exit 0
