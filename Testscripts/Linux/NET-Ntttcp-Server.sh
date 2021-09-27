#!/bin/bash

# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

#######################################################################
#
# ntttcp_server.sh
#         This script starts ntttcp in server mode on dependency VM.
#######################################################################
cd ~

. net_constants.sh || {
    echo "unable to source net_constants.sh!"
    echo "TestAborted" > state.txt
    exit 1
}
# Source utils.sh
. utils.sh || {
    echo "unable to source utils.sh!"
    echo "TestAborted" > state.txt
    exit 1
}
# Source constants file and initialize most common variables
UtilsInit

if [ "${STATIC_IP2:-UNDEFINED}" = "UNDEFINED" ]; then
    LogMsg "The test parameter STATIC_IP2 is not defined in constants file!"
    SetTestStateAborted
    exit 1
fi

# Install the dependencies
update_repos
install_package "wget make gcc"

#install ntttcp
install_ntttcp

#Distro specific setup
GetDistro
case "$DISTRO" in
debian*|ubuntu*)
    service ufw status
    if [ $? -ne 3 ]; then
        LogMsg "Disabling firewall on Ubuntu.."
        iptables -t filter -F
        if [ $? -ne 0 ]; then
            LogErr "Failed to stop ufw."
            return 1
        fi
        iptables -t nat -F
        if [ $? -ne 0 ]; then
            LogErr "Failed to stop ufw."
            return 1
        fi
    fi;;
redhat_5|redhat_6)
    LogMsg "Check iptables status on RHEL."
    service iptables status
    if [ $? -ne 3 ]; then
        LogMsg "Disabling firewall on Redhat.."
        iptables -t filter -F
        if [ $? -ne 0 ]; then
            LogErr "Failed to flush iptables rules."
            return 1
        fi
        iptables -t nat -F
        if [ $? -ne 0 ]; then
            LogErr "Failed to flush iptables nat rules."
            return 1
        fi
        ip6tables -t filter -F
        if [ $? -ne 0 ]; then
            LogErr "Failed to flush ip6tables rules."
            return 1
        fi
        ip6tables -t nat -F
        if [ $? -ne 0 ]; then
            LogErr "Failed to flush ip6tables nat rules."
            return 1
        fi
    fi;;
redhat_7)
    LogMsg "Check iptables status on RHEL."
    systemctl status firewalld
    if [ $? -ne 3 ]; then
        LogMsg "Disabling firewall on Redhat 7.."
        systemctl disable firewalld
        if [ $? -ne 0 ]; then
            LogErr "Failed to stop firewalld."
            return 1
        fi
        systemctl stop firewalld
        if [ $? -ne 0 ]; then
            LogErr "Failed to turn off firewalld."
            return 1
        fi
    fi
    LogMsg "Check iptables status on RHEL 7."
    service iptables status
    if [ $? -ne 3 ]; then
        iptables -t filter -F
        if [ $? -ne 0 ]; then
            LogErr "Failed to flush iptables rules."
            return 1
        fi
        iptables -t nat -F
        if [ $? -ne 0 ]; then
            LogErr "Failed to flush iptables nat rules."
            return 1
        fi
        ip6tables -t filter -F
        if [ $? -ne 0 ]; then
            LogErr "Failed to flush ip6tables rules."
            return 1
        fi
        ip6tables -t nat -F
        if [ $? -ne 0 ]; then
            LogErr "Failed to flush ip6tables nat rules."
            return 1
        fi
    fi;;
suse_12)
    LogMsg "Check iptables status on SLES."
    service SuSEfirewall2 status
    if [ $? -ne 3 ]; then
        iptables -F;
        if [ $? -ne 0 ]; then
            LogErr "Failed to flush iptables rules."
            return 1
        fi
        service SuSEfirewall2 stop
        if [ $? -ne 0 ]; then
            LogErr "Failed to stop iptables."
            return 1
        fi
        chkconfig SuSEfirewall2 off
        if [ $? -ne 0 ]; then
            LogErr "Failed to turn off iptables."
            return 1
        fi
        iptables -t filter -F
        iptables -t nat -F
    fi;;
esac

# Start ntttcp server instances
LogMsg "Starting ntttcp in server mode."

echo "ntttcp Running" > state.txt
LogMsg "ntttcp server instances are now ready to run."
ulimit -n 204800 && ntttcp -r${STATIC_IP2} -P 64 -t 300 -e -W 1 -C 1 >> ~/summary.log
if [ $? -ne 0 ]; then
    LogMsg "Unable to start ntttcp in server mode."
    SetTestStateFailed
    exit 1
fi
