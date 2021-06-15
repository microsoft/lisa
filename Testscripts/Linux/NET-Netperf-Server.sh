#!/bin/bash

# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

#######################################################################
#
# netperf_server.sh
#         This script starts netperf in server mode on dependency VM.
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

#Download NETPERF
wget https://github.com/HewlettPackard/netperf/archive/netperf-2.7.0.tar.gz > /dev/null 2>&1
if [ $? -ne 0 ]; then
    LogMsg "Unable to download netperf."
    SetTestStateFailed
    exit 1
fi
tar -xvf netperf-2.7.0.tar.gz > /dev/null 2>&1

#Get the root directory of the tarball
rootDir="netperf-netperf-2.7.0"
cd ${rootDir}

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
mariner)
        install_package "make kernel-headers binutils glibc-devel zlib-devel"
    ;;
esac
./configure > /dev/null 2>&1
if [ $? -ne 0 ]; then
    LogMsg "Unable to configure make file for netperf."
    SetTestStateFailed
    exit 1
fi
make > /dev/null 2>&1
if [ $? -ne 0 ]; then
    LogMsg "Unable to build netperf."
    SetTestStateFailed
    exit 1
fi
make install > /dev/null 2>&1
if [ $? -ne 0 ]; then
    LogMsg "Unable to install netperf."
    SetTestStateFailed
    exit 1
fi
export PATH="/usr/local/bin:${PATH}"
#go back to test root folder
cd ~

# Start netperf server instances
LogMsg "Starting netperf in server mode."

echo "netperfRunning" > state.txt
LogMsg "Netperf server instances are now ready to run."
netserver -L ${STATIC_IP2} >> ~/summary.log
if [ $? -ne 0 ]; then
    LogMsg "Unable to start netperf in server mode."
    SetTestStateFailed
    exit 1
fi
