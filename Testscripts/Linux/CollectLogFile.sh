#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
export PATH="/sbin:/bin:/usr/sbin:/usr/bin"
dmesg > `hostname`-dmesg.txt
cp /var/log/waagent.log `hostname`-waagent.log.txt
uname -r > `hostname`-kernelVersion.txt
uptime -s > `hostname`-uptime.txt || echo "UPTIME_COMMAND_ERROR" > `hostname`-uptime.txt
modinfo hv_netvsc > `hostname`-lis.txt
release=`cat /etc/*release*`
if [ -f /etc/redhat-release ] ; then
        echo "/etc/redhat-release detected"
        if [[ "$release" =~ "Oracle" ]] ; then
                cat /etc/os-release | grep ^PRETTY_NAME | sed 's/"//g' | sed 's/PRETTY_NAME=//g' > `hostname`-distroVersion.txt
        else
                cat /etc/redhat-release > `hostname`-distroVersion.txt
        fi
elif [ -f /etc/SuSE-release ] ; then
        echo "/etc/SuSE-release detected"
        cat /etc/os-release | grep ^PRETTY_NAME | sed 's/"//g' | sed 's/PRETTY_NAME=//g' > `hostname`-distroVersion.txt
elif [[ "$release" =~ "UBUNTU" ]] || [[ "$release" =~ "Ubuntu" ]] || [[ "$release" =~ "Debian" ]]; then
        NAME=`cat /etc/os-release | grep ^NAME= | sed 's/"//g' | sed 's/NAME=//g'`
        VERSION=`cat /etc/os-release | grep ^VERSION= | sed 's/"//g' | sed 's/VERSION=//g'`
        echo "$NAME $VERSION" > `hostname`-distroVersion.txt
elif [ -e /usr/share/clear/version ]; then
        NAME=`cat /usr/lib/os-release | grep ^PRETTY_NAME | sed 's/"//g' | sed 's/PRETTY_NAME=//g'`
        VERSION=`cat /usr/lib/os-release | grep ^VERSION= | sed 's/"//g' | sed 's/VERSION=//g'`
        echo "$NAME $VERSION" > `hostname`-distroVersion.txt
else
        echo "unknown" > `hostname`-distroVersion.txt
        echo $release > `hostname`-unknownDistro.txt
fi
exit 0