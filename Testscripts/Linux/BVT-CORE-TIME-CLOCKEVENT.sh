#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

########################################################################
#
# Core_Time_Clockevent.sh
#
# Description:
#	This script was created to check current clockevent device and unbind func.
#
################################################################
# Source utils.sh
. utils.sh || {
    echo "Error: unable to source utils.sh!"
    echo "TestAborted" > state.txt
    exit 0
}

# Source constants file and initialize most common variables
UtilsInit

#
# Check the file of current_device for clockevent
#
CheckClockEvent()
{
    current_clockevent="/sys/devices/system/clockevents/clockevent0/current_device"
    if ! [[ $(find $current_clockevent -type f -size +0M) ]]; then
        LogMsg "Test Failed. No file was found current_device greater than 0M."
        SetTestStateFailed
        exit 0
    else
        __clockevent=$(cat $current_clockevent)
        if [[ "$__clockevent" == "Hyper-V clockevent" ]]; then
            LogMsg "Test successful. Proper file was found. Clockevent file content is: $__clockevent"
        else
            LogMsg "Test failed. Proper file was NOT found."
            SetTestStateFailed
            exit 0
        fi
    fi
}

# check timer info in /proc/timer_list compares vcpu count
CheckTimerInfo()
{
    timer_list="/proc/timer_list"
    clockevent_count=$(grep -c "Hyper-V clockevent" < $timer_list)
    event_handler_count=$(grep -c "hrtimer_interrupt" < $timer_list)
    if [ "$clockevent_count" -eq "$VCPU" ] && [ "$event_handler_count" -eq "$VCPU" ]; then
        LogMsg "Test successful. Check both clockevent count and event_handler count equal vcpu count."
    else
        LogMsg "Test failed. Check clockevent count or event_handler count does not equal vcpu count."
        SetTestStateFailed
        exit 0
    fi
}

# unbind clockevent "Hyper-V clockevent"
UnbindClockEvent()
{
    if [ "$VCPU" -gt "1" ]; then
        LogMsg "SMP vcpus not support unbind clockevent"
    else
        clockevent_unbind_file="/sys/devices/system/clockevents/clockevent0/unbind_device"
        clockevent="Hyper-V clockevent"
        if echo "$clockevent" > $clockevent_unbind_file
        then
            _clockevent=$(cat /sys/devices/system/clockevents/clockevent0/current_device)
            if [ "$_clockevent" == "lapic" ]; then
                LogMsg "Test successful. After unbind, current clockevent device is $_clockevent"
            else
                LogMsg "Test failed. After unbind, current clockevent device is $_clockevent"
                SetTestStateFailed
                exit 0
            fi
        else
            LogMsg "Test failed. Can not unbind '$clockevent'"
            SetTestStateFailed
            exit 0
        fi
    fi
}

#
# MAIN SCRIPT
#
GetDistro
case $DISTRO in
    redhat_6 | centos_6)
        LogMsg "WARNING: $DISTRO does not support Hyper-V clockevent."
        SetTestStateAborted
        exit 0
        ;;
    redhat_7|redhat_8|centos_7|centos_8|fedora*)
        CheckClockEvent
        CheckTimerInfo
        UnbindClockEvent
        ;;
    ubuntu* )
        CheckClockEvent
        CheckTimerInfo
        UnbindClockEvent
        ;;
    *)
        msg="ERROR: Distro '$DISTRO' not supported"
        LogMsg "${msg}"
        SetTestStateFailed
        exit 0
        ;;
esac
LogMsg "Test completed successfully."
SetTestStateCompleted
exit 0
