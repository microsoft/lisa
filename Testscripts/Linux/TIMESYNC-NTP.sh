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

function check_cmd_result() {
# the first argument: $? from the latest command execution.
# the second argument: The message for the success case
# the third argument: The message for the failed case

    cmd_result=$1
    success_msg=$2
    failed_msg=$3
    if [ $cmd_result -ne 0  ]; then
        LogErr "$failed_msg"
        SetTestStateAborted
        exit 0
    else
        LogMsg "$success_msg"
    fi
}
# Source constants file and initialize most common variables
UtilsInit
GetDistro
# Try to restart ntp. If it fails we try to install it.
case $DISTRO in
    redhat_*|centos_*|almalinux*|mariner)
        # RHEL 8 does not support ntp, skip test
        if [[ $DISTRO == "centos_8" || $DISTRO == "redhat_8" || $DISTRO == "almalinux_8" ]]; then
            LogMsg "$DISTRO does not support ntp. Test skipped. "
            SetTestStateSkipped
            exit 0
        fi
        # Check if ntpd is running
        service ntpd restart || systemctl restart ntpd
        if [ $? -ne 0 ];then
            LogMsg "Info: ntpd not installed. Trying to install..."
            update_repos
            yum install -y ntp
            check_cmd_result $? "Installed ntpd successfully" "Unable to install ntpd. Aborting"

            yum install -y chkconfig
            chkconfig ntpd on
            check_cmd_result $? "Successfully configure ntpd" "Unable to chkconfig ntpd on. Aborting"

            ntpdate pool.ntp.org
            check_cmd_result $? "Successfully update ntpdate to pool.ntp.org" "Unable to set ntpdate. Aborting"

            service ntpd start || systemctl restart ntpd
            check_cmd_result $? "Successfully started ntpd service" "Unable to start ntpd. Aborting"
        fi
        if [[ $DISTRO == "mariner" ]]; then
            echo "
            server 0.pool.ntp.org
            server 1.pool.ntp.org
            server 2.pool.ntp.org
            server 3.pool.ntp.org
            " >> /etc/ntp.conf
        fi
        # set rtc clock to system time & restart ntpd
        hwclock --systohc
        check_cmd_result $? "Successfully synced RTC clock" "Unable to sync RTC clock to system time. Aborting"

        service ntpd restart || systemctl restart ntpd
        check_cmd_result $? "Successfully restarted ntpd daemon" "Unable to start ntpd. Aborting"
    ;;
    ubuntu*)
        # Check if ntp is running
        service ntp restart
        if [ $? -ne 0 ]; then
            LogMsg "ntp is not installed. Trying to install..."
            update_repos
            install_package ntp
            which ntpd
            check_cmd_result $? "Failed to install ntpd" "ntpd installed successfully"
        fi

        # set rtc clock to system time & restart ntpd
        hwclock --systohc
        check_cmd_result $? "Successfully synced RTC clock to the system" "Unable to sync RTC clock to system time. Aborting"

        service ntp restart
        check_cmd_result $? "Successfully restarted ntpd daemon" "Unable to restart ntpd. Aborting"
    ;;
    suse*|sles*)
        #In SLES 12 service name is ntpd, in SLES 11 is ntp
        if  [[ $DISTRO == "suse_11" ]]; then
            srv="ntp"
        else
            srv="ntpd"
        fi
        LogMsg "Time service daemon name is $srv"

        service $srv restart
        if [ $? -ne 0  ]; then
            LogMsg "ntp is not installed. Trying to install ..."
            update_repos
            zypper --non-interactive install ntp
            check_cmd_result $? "Successfully installed ntpd daemon" "Unable to install ntp. Aborting"
        fi

        # Set rtc clock to system time
        hwclock --systohc
        check_cmd_result $? "Successfully synced initial RTC clock to system time" "Unable to sync initial RTC clock to system time. Aborting"

        # Edit ntp Server config and set the timeservers
        sed -i 's/^server.*/ /g' /etc/ntp.conf
        echo "
        server 0.pool.ntp.org
        server 1.pool.ntp.org
        server 2.pool.ntp.org
        server 3.pool.ntp.org
        " >> /etc/ntp.conf

        # Set rtc clock to system time
        hwclock --systohc
        check_cmd_result $? "Successfully synced secondary RTC clock to system time" "Unable to sync secondary RTC clock to system time. Aborting"

        # Restart ntp service
        service $srv restart
        check_cmd_result $? "Successfully restarted $srv daemon" "Unable to restart $srv. Aborting"
    ;;
    coreos)
        # Refer to https://github.com/coreos/docs/blob/master/os/configuring-date-and-timezone.md#time-synchronization
        systemctl stop systemd-timesyncd
        systemctl mask systemd-timesyncd
        systemctl enable ntpd
        systemctl start ntpd
        check_exit_status "Start ntpd service"
        # set rtc clock to system time & restart ntpd
        hwclock --systohc
        check_cmd_result $? "ssfully synced RTC clock to system time" "Unable to sync RTC clock to system time. Aborting"

        systemctl restart ntpd
        check_cmd_result $? "Successfully restarted ntpd daemon" "Unable to restart ntpd. Aborting"
    ;;
    *)
    LogErr "Distro not supported. Aborting"
    UpdateSummary "Distro not supported. Aborting"
    SetTestStateAborted
    exit 0
    ;;
esac

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
