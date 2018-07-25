#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

########################################################################
#
# Synopsis
#     This script tests NTP time syncronization.
#
# Description
#     This script was created to automate the testing of a Linux
#     Integration services. It enables Network Time Protocol and 
#     checks if the time is in sync.
#
########################################################################

maxdelay=5.0                        # max offset in seconds.
zerodelay=0.0                       # zero
loopbackIP="127.0.0.1"              # IP to force NTPD to listen on IPv4

# Source utils.sh
. utils.sh || {
    echo "ERROR: unable to source utils.sh!"
    echo "TestAborted" > state.txt
    exit 0
}

# Source constants file and initialize most common variables
UtilsInit

# Try to restart NTP. If it fails we try to install it.
if is_fedora ; then
    # Check if ntpd is running
    if ! service ntpd restart
    then
        LogMsg "Info: NTPD not installed. Trying to install..."
        if ! yum install -y ntp ntpdate
        then
            LogMsg "ERROR: Unable to install ntpd. Aborting"
            SetTestStateAborted
            exit 0
        fi
        
        if ! chkconfig ntpd on
        then
            LogMsg "ERROR: Unable to chkconfig ntpd on. Aborting"
            SetTestStateAborted
            exit 0
        fi
        
        if ! ntpdate pool.ntp.org
        then
            LogMsg "ERROR: Unable to set ntpdate. Aborting"
            SetTestStateAborted
            exit 0
        fi
        
        if ! service ntpd start
        then
            LogMsg "ERROR: Unable to start ntpd. Aborting"
            SetTestStateAborted
            exit 0
        fi
        LogMsg "Info: NTPD has been installed succesfully!"
    fi

    # set rtc clock to system time & restart NTPD
    if ! hwclock --systohc
    then
        LogMsg "ERROR: Unable to sync RTC clock to system time. Aborting"
        SetTestStateAborted
        exit 0
    fi

    if ! service ntpd restart
    then
        LogMsg "ERROR: Unable to start ntpd. Aborting"
        SetTestStateAborted
        exit 0
    fi

elif is_ubuntu ; then
    # Check if ntp is running
    if ! service ntp restart
    then
        LogMsg "NTP is not installed. Trying to install..."
        apt-get update
        if ! apt-get install ntp -y
        then
            LogMsg "ERROR: Unable to install ntp. Aborting"
            SetTestStateAborted
            exit 0
        fi
        LogMsg "Info: NTPD has been installed succesfully!"
    fi

    # set rtc clock to system time & restart NTPD
    if ! hwclock --systohc
    then
        LogMsg "ERROR: Unable to sync RTC clock to system time. Aborting"
        SetTestStateAborted
        exit 0
    fi

    if ! service ntp restart
    then
        LogMsg "ERROR: Unable to restart ntpd. Aborting"
        SetTestStateAborted
        exit 0
    fi

elif is_suse ; then
    #In SLES 12 service name is ntpd, in SLES 11 is ntp
    os_RELEASE=$(echo "$os_RELEASE" | sed -e 's/^\(.\{2\}\).*/\1/')
    if  [ "$os_RELEASE" -eq 11 ]; then
        srv="ntp"
    else
        srv="ntpd"
    fi

    service $srv restart
    if ! service $srv restart
    then
        LogMsg "NTP is not installed. Trying to install ..."
        zypper --non-interactive install ntp
        if ! zypper --non-interactive install ntp
        then
            LogMsg "ERROR: Unable to install ntp. Aborting"
            SetTestStateAborted
            exit 0
        fi
        LogMsg "NTP installed succesfully!"
    fi

    service $srv stop

    # Edit NTP Server config and set the timeservers
    sed -i 's/^server.*/ /g' /etc/ntp.conf
    echo "
    server 0.pool.ntp.org
    server 1.pool.ntp.org
    server 2.pool.ntp.org
    server 3.pool.ntp.org
    " >> /etc/ntp.conf
    if [[ $? -ne 0 ]]; then
        LogMsg "ERROR: Unable to sync RTC clock to system time. Aborting"
        SetTestStateAborted
        exit 0
    fi

    # Set rtc clock to system time
    hwclock --systohc 
    if ! hwclock --systohc 
    then
        LogMsg "ERROR: Unable to sync RTC clock to system time. Aborting"
        SetTestStateAborted
        exit 0
    fi

    # Restart NTP service
    service $srv restart
    if ! service $srv restart
    then
        LogMsg "ERROR: Unable to restart ntpd. Aborting"
        SetTestStateAborted
        exit 0
    fi

else # other distro
    LogMsg "Warning: Distro not suported. Aborting"
    UpdateSummary "Warning: Distro not suported. Aborting"
    SetTestStateAborted
    exit 0
fi

# Show a list of peers to check if the NTP daemon is running
ntpq -p $loopbackIP
if ! ntpq -p $loopbackIP 
then
    LogMsg "Error: Unable to query NTP deamon!"
    SetTestStateAborted
    exit 0
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
        LogMsg "ERROR: ntpq returned $ntpqErr. Aborting test."
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
            LogMsg "ERROR: Delay cannot be 0.000; Please check NTP sync manually."
            SetTestStateAborted
            exit 0
        elif [[ 0 -ne $check ]] ; then    
            LogMsg "ERROR: NTP Time out of sync. Test Failed"
            LogMsg "NTP offset is $delay seconds."
            SetTestStateFailed
            exit 0
        fi
    fi
    sleep 1
done

# If we reached this point, time is synced.
LogMsg "Test passed. NTP offset is $delay seconds."
SetTestStateCompleted
exit 0
