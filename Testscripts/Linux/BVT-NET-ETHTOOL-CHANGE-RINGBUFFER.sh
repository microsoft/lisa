#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

#############################################################################
#
# Ring_buffer_size.sh
# Description:
#    This script will first check the existence of ethtool on vm and that
#    the ring settings from ethtool are supported.
#    Then it will try to set new size of ring buffer for RX-Received packets
#    and TX-Trasmitted packets.
#    If the new values were set then the test is passed
#
#############################################################################
declare -i __iterator=0

# Source utils.sh
. utils.sh || {
    echo "Error: unable to source utils.sh!"
    echo "TestAborted" > state.txtz
    exit 0
}

# Source constants file and initialize most common variables
UtilsInit

# Check if ethtool exist and install it if not
VerifyIsEthtool

if ! GetSynthNetInterfaces; then
    msg="ERROR: No synthetic network interfaces found"
    LogMsg "$msg"
    SetTestStateFailed
    exit 0
fi

# Check if kernel support ring settings from ethtool
sts=$(ethtool -g "${SYNTH_NET_INTERFACES[@]}" 2>&1)
if [[ "$sts" = *"Operation not supported"* ]]; then
    LogMsg "$sts"
    LogMsg "Operation not supported. Test Skipped."
    SetTestStateAborted
    exit 0
fi

# Take the initial values
rx_value=$(echo "$sts" | grep RX: | sed -n 2p | grep -o '[0-9]*')
tx_value=$(echo "$sts" | grep TX: | sed -n 2p | grep -o '[0-9]*')
LogMsg "RX: ${rx_value} | TX: ${tx_value}."

# Try to change RX and TX with new values
if ! ethtool -G "${SYNTH_NET_INTERFACES[@]}" rx "$rx" tx "$tx"; then
    LogMsg "Cannot change RX and TX values."
    SetTestStateFailed
    exit 0
fi

# Take the values after changes
new_sts=$(ethtool -g "${SYNTH_NET_INTERFACES[$__iterator]}" 2>&1)
rx_modified=$(echo "$new_sts" | grep RX: | sed -n 2p | grep -o '[0-9]*')
tx_modified=$(echo "$new_sts" | grep TX: | sed -n 2p | grep -o '[0-9]*')
LogMsg "RX_modified: $rx_modified | TX_modified: $tx_modified."

# Compare provided values with values after changes
if [ "$rx_modified" == "$rx" ] && [ "$tx_modified" == "$tx" ]; then
    LogMsg "Successfully changed RX and TX values on ${SYNTH_NET_INTERFACES[*]}."
    SetTestStateCompleted
    exit 0
else
    LogMsg "The values provided aren't matching the real values of RX and TX. Check the logs."
    SetTestStateFailed
    exit 0
fi
