#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

########################################################################
#
# Synopsis
#     This script tests ntp time synchronization.
#
# Description
#     This script was created to automate the testing of a Linux
#     Integration services. It enables Network Time Protocol and
#     checks if the time is in sync.
#
########################################################################

maxdelay=5.0                        # max offset in seconds.
zerodelay=0.0                       # zero
loopbackIP="127.0.0.1"              # IP to force ntpd to listen on IPv4

# Source utils.sh
. utils.sh || {
    echo "ERROR: unable to source utils.sh!"
    echo "TestAborted" > state.txt
    exit 0
}

# Source constants file and initialize most common variables
UtilsInit

# Try to restart ntp. If it fails we try to install it.
if [ is_fedora ]; then
    # RHEL 8 does not support ntp, skip test
    if [[ $os_RELEASE =~ 8.* ]]; then
        LogMsg "Info: $os_VENDOR $os_RELEASE does not support ntp. Test skipped. "
        SetTestStateSkipped
        exit 0
    fi
    # Check if ntpd is running
    if [ ! service ntpd restart ];then
        LogMsg "Info: ntpd not installed. Trying to install..."
        update_repos
        if [ ! yum install -y ntp ]; then
            LogErr "Unable to install ntpd. Aborting"
            SetTestStateAborted
            exit 0
        else
            LogMsg "Installed ntpd successfully"
        fi

        if [ ! chkconfig ntpd on ]; then
            LogErr "Unable to chkconfig ntpd on. Aborting"
            SetTestStateAborted
            exit 0
        else
            LogMsg "Successfull configure ntpd"
        fi

        if [ ! ntpdate pool.ntp.org ]; then
            LogErr "Unable to set ntpdate. Aborting"
            SetTestStateAborted
            exit 0
        else
            LogMsg "Successfull update ntpdate to pool.ntp.org"
        fi

        if [ ! service ntpd start ]; then
            LogErr "Unable to start ntpd. Aborting"
            SetTestStateAborted
            exit 0
        else
            LogMsg "Successfully started ntpd service"
        fi
    fi

    # set rtc clock to system time & restart ntpd
    if [ ! hwclock --systohc ]; then
        LogErr "Unable to sync RTC clock to system time. Aborting"
        SetTestStateAborted
        exit 0
    else
        LogMsg "Successfully synced RTC clock"
    fi

    if [ ! service ntpd restart ];then
        LogErr "Unable to start ntpd. Aborting"
        SetTestStateAborted
        exit 0
    else
        LogMsg "Successfully restarted ntpd daemon"
    fi

elif [ is_ubuntu ] ; then
    # Check if ntp is running
    if [ ! service ntp restart ]; then
        LogMsg "ntp is not installed. Trying to install..."
        update_repos
        install_package ntp
        which ntpd
        if [ $? -eq 0 ]; then
            LogMsg "ntpd installed successfully"
        else
            LogErr "Failed to install ntpd"
            SetTestStateAborted
            exit 0
        fi
    fi

    # set rtc clock to system time & restart ntpd
    if [ ! hwclock --systohc ]; then
        LogErr "Unable to sync RTC clock to system time. Aborting"
        SetTestStateAborted
        exit 0
    else
        LogMsg "Successfully synced RTC clock to the system"
    fi

    if [ ! service ntp restart ]; then
        LogErr "Unable to restart ntpd. Aborting"
        SetTestStateAborted
        exit 0
    else
        LogMsg "Successfully restarted ntpd daemon"
    fi

elif [ is_suse ]; then
    #In SLES 12 service name is ntpd, in SLES 11 is ntp
    os_RELEASE=$(echo "$os_RELEASE" | sed -e 's/^\(.\{2\}\).*/\1/')
    if  [ "$os_RELEASE" -eq 11 ]; then
        srv="ntp"
    else
        srv="ntpd"
    fi
    LogMsg "Time service daemon name is $srv"

    service $srv restart
    if [ ! service $srv restart ]; then
        LogMsg "ntp is not installed. Trying to install ..."
        update_repos
        zypper --non-interactive install ntp
        if [ ! zypper --non-interactive install ntp ]; then
            LogErr "Unable to install ntp. Aborting"
            SetTestStateAborted
            exit 0
        else
            LogMsg "Successfully installed ntpd daemon"
        fi
    fi

    service $srv stop

    # Edit ntp Server config and set the timeservers
    sed -i 's/^server.*/ /g' /etc/ntp.conf
    echo "
    server 0.pool.ntp.org
    server 1.pool.ntp.org
    server 2.pool.ntp.org
    server 3.pool.ntp.org
    " >> /etc/ntp.conf
    if [[ $? -ne 0 ]]; then
        LogErr "Unable to sync RTC clock to system time. Aborting"
        SetTestStateAborted
        exit 0
    else
        LogMsg "Successfully synced RTC clock to system time"
    fi

    # Set rtc clock to system time
    hwclock --systohc
    if [ ! hwclock --systohc ]; then
        LogErr "Unable to sync RTC clock to system time. Aborting"
        SetTestStateAborted
        exit 0
    else
        LogMsg "Successfully synced RTC clock to system time"
    fi

    # Restart ntp service
    service $srv restart
    if [ ! service $srv restart]; then
        LogErr "Unable to restart $srv. Aborting"
        SetTestStateAborted
        exit 0
    else
        LogMsg "Successfull restarted $srv daemon"
    fi

elif [[ $(detect_linux_distribution) == coreos ]]; then
    # Refer to https://github.com/coreos/docs/blob/master/os/configuring-date-and-timezone.md#time-synchronization
    systemctl stop systemd-timesyncd
    systemctl mask systemd-timesyncd
    systemctl enable ntpd
    systemctl start ntpd
    check_exit_status "Start ntpd service"
    # set rtc clock to system time & restart ntpd
    if [ ! hwclock --systohc ]; then
        LogErr "Unable to sync RTC clock to system time. Aborting"
        SetTestStateAborted
        exit 0
    else
        LogMsg "Successfully synced RTC clock to system time"
    fi

    if [ ! systemctl restart ntpd ];then
        LogErr "Unable to restart ntpd. Aborting"
        SetTestStateAborted
        exit 0
    else
        LogMsg "Successfully restarted ntpd daemon"
    fi

else # other distro
    LogErr "Distro not supported. Aborting"
    UpdateSummary "Distro not supported. Aborting"
    SetTestStateAborted
    exit 0
fi

# check if the ntp daemon is running
timeout=50
while [ $timeout -ge 0 ]; do
    ntpdVal=$(ntpq -p $loopbackIP)
    if [ -n "$ntpdVal" ] ; then
        break
    else
        LogMsg "Wait for ntp daemon is running"
        timeout=$((timeout-5))
        sleep 5
    fi
done

if [ -z "$ntpdVal" ];then
    LogErr "Unable to query ntp deamon!"
    SetTestStateAborted
    exit 0
else
    LogMsg "Verified ntpd deamon running"
fi

# Variables for while loop. stopTest is the time until the test will run
isOver=false
secondsToRun=1800
stopTest=$(( $(date +%s) + secondsToRun ))

while [ $isOver == false ]; do
    # 'ntpq -c rl' returns the offset between the ntp server and internal clock
    delay=$(ntpq -c rl $loopbackIP | grep offset= | awk -F "=" '{print $3}' | awk '{print $1}')
    delay=$(echo "$delay" | sed s'/.$//')

    # If the above value is not a number it means the output is an error message and exit loop
    re='^-?[0-9]+([.][0-9]+)?$'
    if ! [[ $delay =~ $re ]] ; then
        ntpqErr="$(ntpq -c rl $loopbackIP 2>&1)"
        LogErr "ntpq returned $ntpqErr. Aborting test."
        SetTestStateAborted
        isOver=true
        exit 0
    fi

    # Transform from milliseconds to seconds
    delay=$(echo "$delay" 1000 | awk '{ print $1/$2 }')

    # Using awk for float comparison
    check=$(echo "$delay $maxdelay" | awk '{if ($1 < $2) print 0; else print 1}')

    # Also check if delay is 0.0
    checkzero=$(echo "$delay $zerodelay" | awk '{if ($1 == $2) print 0; else print 1}')

    # Check delay for changes; if it matches the requirements, the loop will end
    if [[ $checkzero -ne 0 ]] && \
       [[ $check -eq 0 ]]; then
        isOver=true
    fi

    # The loop will run for half an hour if delay doesn't match the requirements
    if  [[ $(date +%s) -gt $stopTest ]]; then
        isOver=true
        if [[ $checkzero -eq 0 ]]; then
            # If delay is 0, something is wrong, so we abort.
            LogErr "Delay cannot be 0.000; Please check ntp sync manually."
            SetTestStateAborted
            exit 0
        elif [[ 0 -ne $check ]] ; then
            LogErr "ntp time out of sync. Test Failed"
            LogErr "ntp offset is $delay seconds."
            SetTestStateFailed
            exit 0
        fi
    fi
    sleep 1
done

# If we reached this point, time is synced.
LogMsg "Test passed. ntp offset is $delay seconds."
SetTestStateCompleted
exit 0
