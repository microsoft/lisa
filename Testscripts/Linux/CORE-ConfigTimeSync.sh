#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

. utils.sh || {
    echo "Error: unable to source utils.sh!"
    exit 0
}

# Source constants file and initialize most common variables
. constants.sh || {
    LogErr "Error: unable to source constants.sh!"
    exit 0
}

UtilsInit

CheckPTPSupport()
{
    # Check for ptp support
    ptp=$(cat /sys/class/ptp/ptp0/clock_name)
    if [ "$ptp" != "hyperv" ]; then
        LogErr "PTP not supported for current distro."
        ptp="off"
    fi
}

ConfigRhel()
{
    chronyd -v
    if [ $? -ne 0 ]; then
        yum_install chrony
        if [ $? -ne 0 ]; then
            LogErr "Failed to install chrony"
            SetTestStateFailed
            exit 0
        fi
    fi
    
    CheckPTPSupport
    if [[ $ptp == "hyperv" ]]; then
        grep "refclock PHC /dev/ptp0 poll 3 dpoll -2 offset 0" /etc/chrony.conf
        if [ $? -ne 0 ]; then
            echo "refclock PHC /dev/ptp0 poll 3 dpoll -2 offset 0" >> /etc/chrony.conf
        fi
    fi

    service chronyd restart
    if [ $? -ne 0 ]; then
        LogErr "Chronyd service failed to restart"
    fi
    
    if [[ $Chrony == "off" ]]; then
        service chronyd stop
        if [ $? -ne 0 ]; then
            LogErr "Unable to stop chronyd"
            SetTestStateFailed
            exit 0
        fi
        service ntpd stop
        if [ $? -ne 0 ]; then
            LogErr "Unable to stop NTPD"
            SetTestStateFailed
            exit 0
        fi
    fi    
}

ConfigSles()
{
    chronyd -v
    if [ $? -ne 0 ]; then
        zypper_install -y chrony
        if [ $? -ne 0 ]; then
            LogErr "Failed to install chrony"
            SetTestStateFailed
            exit 0
        fi
    fi

    CheckPTPSupport
    if [[ $ptp == "hyperv" ]]; then
        grep "refclock PHC /dev/ptp0 poll 3 dpoll -2 offset 0" /etc/chrony.conf
        if [ $? -ne 0 ]; then
            echo "refclock PHC /dev/ptp0 poll 3 dpoll -2 offset 0" >> /etc/chrony.conf
        fi
    fi

    systemctl restart chronyd
    if [ $? -ne 0 ]; then
        LogErr "Chronyd service failed to restart"
        SetTestStateFailed
        exit 0
    fi

    if [[ $Chrony == "off" ]]; then
        service chronyd stop
        if [ $? -ne 0 ]; then
            LogErr "Unable to stop chronyd"
            SetTestStateFailed
            exit 0
        fi
        service ntpd stop
        if [ $? -ne 0 ]; then
            LogErr "Unable to stop NTPD"
            SetTestStateFailed
            exit 0
        fi
    fi    
}

ConfigUbuntu()
{
    chronyd -v
    if [ $? -ne 0 ]; then
        apt_get_install chrony -y
        if [ $? -ne 0 ]; then
            LogErr "Failed to install chrony"
            SetTestStateFailed
            exit 0
        fi
    fi

    CheckPTPSupport
    if [[ $ptp == "hyperv" ]]; then
        grep "refclock PHC /dev/ptp0 poll 3 dpoll -2 offset 0" /etc/chrony/chrony.conf
        if [ $? -ne 0 ]; then
            echo "refclock PHC /dev/ptp0 poll 3 dpoll -2 offset 0" >> /etc/chrony/chrony.conf
        fi
    fi

    systemctl restart chrony
    if [ $? -ne 0 ]; then
        LogErr "Chronyd service failed to restart"
        SetTestStateFailed
        exit 0
    fi

    if [[ $Chrony == "off" ]]; then
        service chrony stop
        if [ $? -ne 0 ]; then
            LogErr "Unable to stop chrony"
            UpdateTestState $ICA_TESTFAILED
            exit 0
        fi

        service ntp stop
        if [ $? -ne 0 ]; then
            LogErr "Unable to stop NTP"
            SetTestStateFailed
            exit 0
        fi
    fi    
}

GetDistro
case $DISTRO in
    centos* | redhat* | fedora*)
        GetOSVersion 
		if [[ $os_RELEASE.$os_UPDATE =~ ^5.* ]] || [[ $os_RELEASE.$os_UPDATE =~ ^6.* ]] ; then
			UpdateSummary "Skipped config step"
		else
			ConfigRhel
		fi
    ;;
    ubuntu*)
        ConfigUbuntu
    ;;
    suse*)
        ConfigSles
    ;;
     *)
        UpdateSummary "Distro '${distro}' not supported."
    ;;
esac

SetTestStateCompleted
