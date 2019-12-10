#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

#############################################################################
#
# Description:
#    This script will first check the existence of ethtool on vm and will
#    get the RSS hash key and then reset it from ethtool.
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
if ! VerifyIsEthtool; then
    LogErr "Could not find ethtool in the VM"
    SetTestStateFailed
    exit 0
fi

if ! GetSynthNetInterfaces; then
    LogErr "No synthetic network interfaces found"
    SetTestStateFailed
    exit 0
fi

GetRSSHashKey()
{
    rss_hash_key=$(ethtool -x $1 | egrep  ".+:.+:.+.+.+.+.+.+")
    if [ ! $rss_hash_key ]; then
        LogErr "Get RSS hash key failed"
        SetTestStateFailed
        exit 0
    fi
    echo $rss_hash_key
}

net_interface=${SYNTH_NET_INTERFACES[0]}
LogMsg "The synthetic network interface is $net_interface"

# Get RSS hash key
key_before_change=$(GetRSSHashKey "${net_interface}")
LogMsg "RSS hash key of ${net_interface} before change: $key_before_change"

select1="4c:a7:44:02:be:2a:8b:7d:ce:c9:1f:4d:95:80:da:6e:66:64:ef:46:50:9f:4c:7e:1d:e7:24:49:84:41:df:06:6a:a1:8e:d9:30:61:36:5b"
select2="6d:5a:56:da:25:5b:0e:c2:41:67:25:3d:43:a3:8f:b0:d0:ca:2b:cb:ae:7b:30:b4:77:cb:2d:a3:80:30:f2:0c:6a:42:b7:3b:be:ac:01:fa"
if [ $key_before_change != $select1 ]; then
    new_key=$select1
else
    new_key=$select2
fi

# Configure the RSS hash key with the new one
LogMsg "Configure the key of $net_interface with $new_key"
sts=$(ethtool -X "${net_interface}" hkey $new_key 2>&1)
if [[ "$sts" = *"Operation not supported"* ]]; then
    LogErr "$sts"
    LogErr "Operation not supported."
    kernel_version=$(uname -rs)
    LogErr "Configure the RSS hash key from ethtool is not supported on $kernel_version"
    SetTestStateFailed
    exit 0
elif [[ "$sts" = *"Invalid argument"* ]]; then
    LogErr "$sts"
    LogErr "Configure ${net_interface} with $new_key failed"
    SetTestStateFailed
    exit 0
fi

# Check the change really worked
key_after_change=$(GetRSSHashKey "${net_interface}")
if [ $new_key != $key_after_change ]; then
    LogMsg "Expected key:$new_key"
    LogMsg "Current key:$key_after_change"
    LogErr "Configure ${net_interface} with $new_key failed"
    SetTestStateFailed
    exit 0
fi

LogMsg "Configure ${net_interface} with $new_key successfully"
SetTestStateCompleted
exit 0
