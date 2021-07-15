#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

# Function to perform pre-requisite check before starting test
function InstallChronyPackage()
{
    local chronyd_daemon="chronyd"
    [[ -z $chronyc_command ]] && {
        dnf install chrony -y
        [[ $? -ne 0 ]] && {
            # This failure should be treated as FAIL as chrony is default recommendation
            LogErr "InstallDependencies: Failed to install chrony package"
            return ${FAIL_ID}
        }
        chronyc_command="$(type -p chronyc)"
        [[ -z $chronyc_command ]] && return ${FAIL_ID}
    }
    # By default chronyd will should be active but if ntpd is running
    # then chrony may get inactive. In that case start chronyd service
    [[ $(systemctl is-active ntpd) == "active" ]] && {
	LogMsg "InstallDependencies: ntpd is active, stop it"
        systemctl stop ntpd
        systemctl start ${chronyd_daemon}
    }
    return 0
}

# Function to check whether clock is synchronized
function CheckClockSynchronized() {
    local count=0
    local status=$(timedatectl | awk '/System clock synchronized/{print $4}')
    while [[ ("${status}" == "no") && ($count -le 30) ]];do
        sleep 10
        count=$((count + 1))
        LogMsg "Checking for clock sync: count: $count"
        status=$(timedatectl | awk '/System clock synchronized/{print $4}')
    done
    if [[ $count -ge 60 ]];then
        LogErr "Clock not sync after $count * 10 seconds"
        return ${FAIL}
    fi
    return 0
}

# Function to check the different aspect to chrony service
# By default chrony should be enabled and active.
function CheckChronydService()
{
    local chronyd_daemon="chronyd"
    if command -v systemctl > /dev/null;then
        [[ $(systemctl is-enabled ${chronyd_service}) != "enabled" ]] && {
            LogErr "CheckChronydService: chronyd is not enabled"
            return ${FAIL_ID}
        }
        [[ $(systemctl is-active ${chronyd_service}) != "active" ]] && {
            LogErr "CheckChronydService: chronyd is not active"
            return ${FAIL_ID}
        }

        if ! systemctl stop ${chronyd_daemon};then
            LogErr "CheckChronydService: Failed to stop chronyd service"
            return ${FAIL_ID}
        fi
        if ! systemctl start ${chronyd_daemon};then
            LogErr "CheckChronydService: Failed to stop chronyd service"
            return ${FAIL_ID}
        fi
        if ! systemctl restart ${chronyd_daemon};then
            LogErr "CheckChronydService: Failed to stop chronyd service"
            return ${FAIL_ID}
        fi
    else
        LogMsg "CheckChronydService: systemd is not supported"
        return ${SKIP_ID}
    fi
    return 0
}

# Function to check whether ntp sync is enabled or not
function CheckChronyNTPSyncEnabled() {
    # Check sync from ntp service is enabled
    local ref_id=$($chronyc_command tracking | grep "Reference ID")
    ref_id=$(echo "$ref_id" | cut -d: -f2 | awk '{print $1}')
    local leap_status=$($chronyc_command tracking | grep "Leap status" | cut -d: -f2)

    local source=$($chronyc_command tracking | grep "Reference ID" | awk '{print $5}')
    local current_source=$(chronyc sources | grep "\^\*" | awk {'print $2}')
    local online_source_cnt=$(chronyc activity | grep "sources online" | awk '{print $1}')

    ref_id=$(echo $ref_id | tr -d [[:space:]])
    leap_status=$(echo $leap_status | tr -d [[:space:]])

    LogMsg "ref_id = $ref_id leap_status = $leap_status"
    LogMsg "source count = $online_source_cnt"
    LogMsg "current source = $current_source source = $source"

    # Check remote service is valid and not set as local(127.127.01.01)
    [[ ${ref_id} == "00000000" || ${ref_id} == "A7A70101" ]] && {
        LogErr "Invalid ntp server config"
        return 1
    }

    # Leap status should be Normal, Insert second or Delete second
    [[ ${leap_status} == "Notsynchronised" ]] && {
        LogErr "NTP server not synchronized"
        return 1
    }

    # Additional check to make sure ntp sync is enabled.
    # Check the number of online source
    [[ ${online_source_cnt} -eq 0 ]] && {
        LogErr "ntp server sync is not enabled"
        return 1
    }

    [[ ${source} != "($current_source)" ]] && {
        LogMsg "INFO: source mismatch is seen"
    }

    return 0
}

#######################################################################
#
# Main script body
#
#######################################################################

# Source containers_utils.sh
. containers_utils.sh || {
    echo "ERROR: unable to source containers_utils.sh"
    echo "TestAborted" > state.txt
    exit 0
}

UtilsInit
GetDistro

test_status=${SKIP_ID}
case $DISTRO in
    centos* | mariner*)
        chronyd_service="chronyd.service"
        chronyc_command="$(type -p chronyc)"
    ;;
     *)
        LogMsg "WARNING: Distro '${DISTRO}' not supported."
        HandleTestResults ${test_status} "InstallDependencies"
        exit 0
    ;;
esac

test_status=0
InstallChronyPackage; test_status=$?
HandleTestResults ${test_status} "InstallChronyPackage"

CheckChronydService; test_status=$?
HandleTestResults ${test_status} "CheckChronydService"

# Before checking chrony setting and functionality, make
# sure clock is synchronized
CheckClockSynchronized; test_status=$?
HandleTestResults ${test_status} "CheckClockSynchronized"

CheckChronyNTPSyncEnabled; test_status=$?
HandleTestResults ${test_status} "CheckChronyNTPSyncEnabled"

SetTestStateCompleted
exit 0
