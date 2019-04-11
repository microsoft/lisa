#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

# Source utils.sh
. utils.sh || {
    echo "Error: unable to source utils.sh!"
    echo "TestAborted" > state.txt
    exit 0
}

# Source constants file and initialize most common variables
UtilsInit

CheckPTPSupport()
{
    # Check for ptp support
    ptp=$(cat /sys/class/ptp/ptp0/clock_name)
    if [ "$ptp" != "hyperv" ]; then
        LogMsg "PTP not supported for current distro."
        ptp="off"
    fi
}

GetDistro
case $DISTRO in
    centos* | redhat* | fedora*)
        GetOSVersion
        if [[ $os_RELEASE.$os_UPDATE =~ ^5.* ]] || [[ $os_RELEASE.$os_UPDATE =~ ^6.* ]] ; then
            LogMsg "INFO: Skipped config step"
        else
            chrony_config_path="/etc/chrony.conf"
            chrony_service_name="chronyd"
            ntp_service_name="ntpd"
        fi
    ;;
    ubuntu* | debian*)
        #Update required before install
        apt-get update
        chrony_config_path="/etc/chrony/chrony.conf"
        chrony_service_name="chrony"
        ntp_service_name="ntp"
    ;;
    suse*)
        chrony_config_path="/etc/chrony.conf"
        chrony_service_name="chronyd"
        ntp_service_name="ntpd"
    ;;
     *)
        LogMsg "WARNING: Distro '${distro}' not supported."
    ;;
esac

if ! chronyd -v; then
    install_package chrony
fi

CheckPTPSupport
if [[ $ptp == "hyperv" ]]; then
    grep "refclock PHC /dev/ptp0 poll 3 dpoll -2 offset 0" $chrony_config_path
    if [ $? -ne 0 ]; then
        echo "refclock PHC /dev/ptp0 poll 3 dpoll -2 offset 0" >> $chrony_config_path
    fi
fi

service $chrony_service_name restart
if [ $? -ne 0 ]; then
    LogMsg "ERROR: Chronyd service failed to restart"
fi

if [[ $Chrony == "off" ]]; then
    service $chrony_service_name stop
    if [ $? -ne 0 ]; then
        LogMsg "ERROR: Unable to stop chronyd"
        SetTestStateFailed
        exit 1
    fi
    service $ntp_service_name stop
    if [ $? -ne 0 ]; then
        LogMsg "ERROR: Unable to stop NTPD"
        SetTestStateFailed
        exit 1
    fi
fi

SetTestStateCompleted
exit 0
