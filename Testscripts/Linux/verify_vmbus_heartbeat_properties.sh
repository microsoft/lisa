#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

# Description:
# The test performs the following steps:
# 1. Looks for the VMBus heartbeat device properties.
# 2. Checks they can be read and that the folder structure exists.
# 3. Checks that the in_* files are equal to the out_* files when read together
# 4. Checks the interrupts and events files are increasing as we read them

# Source utils.sh
. utils.sh || {
    echo "ERROR: unable to source utils.sh!"
    echo "TestAborted" > state.txt
    exit 0
}

# Source constants file and initialize most common variables
UtilsInit

# Install python 2.7 if missing
which python
if [[ $? -gt 0 ]]; then
	install_package python2
	ln -s /usr/bin/python2.7 /usr/bin/python
fi

# check if lsvmbus exists, or the running kernel does not match installed version of linux-tools
check_lsvmbus

# Get the system path to the Heartbeat device on the VMBus
sys_path=$(lsvmbus -vv | grep -A4 Heartbeat | grep path | awk '{ print $3 }')

if [[ ! -d "$sys_path" ]] || [[ "$sys_path" != "/sys/bus/vmbus/devices/"* ]]; then
    LogErr "Heartbeat device system path [$sys_path] does not exist or is not in the vmbus subsystem."
    SetTestStateFailed
    exit 0
fi

SetTestStateRunning

test_failed=""

# check the file structure exists and that all the files can be read
vmbus_driver_files_default=(channel_vp_mapping class_id client_monitor_conn_id \
client_monitor_latency client_monitor_pending device device_id id in_intr_mask \
in_read_bytes_avail in_read_index in_write_bytes_avail in_write_index modalias \
monitor_id out_intr_mask out_read_bytes_avail out_read_index out_write_bytes_avail \
out_write_index server_monitor_conn_id server_monitor_latency \
server_monitor_pending state uevent vendor)

vmbus_driver_files_upstream=(channel_vp_mapping class_id device device_id id \
in_intr_mask in_read_bytes_avail in_read_index in_write_bytes_avail \
in_write_index modalias out_intr_mask out_read_bytes_avail out_read_index \
out_write_bytes_avail out_write_index state uevent vendor driver_override)

if [ ! -f "$sys_path/driver_override" ]; then
    vmbus_driver_files="$vmbus_driver_files_default"
else
    vmbus_driver_files="$vmbus_driver_files_upstream"
fi
for file in "${vmbus_driver_files[@]}"; do
    if [ ! -f "$sys_path/$file" ]; then
        LogErr "$sys_path/$file does not exist"
        test_failed="true"
    fi
    if ! cat "$sys_path/$file" > /dev/null; then
        LogErr "Cannot read file: $sys_path/$file"
        test_failed="true"
    fi
done

# check the 1st channel of the device
channel_path="$sys_path/channels/$(ls -1 $sys_path/channels | head -1)"
if [ -d "$channel_path" ]; then
    vmbus_channel_files_default=(cpu events in_mask interrupts latency out_mask pending read_avail write_avail)
    vmbus_channel_files_upstream=(cpu events in_mask interrupts out_mask read_avail write_avail)
    if [ -f "$channel_path/monitor_id" ]; then
        vmbus_channel_files="$vmbus_channel_files_default"
    else
        vmbus_channel_files="$vmbus_channel_files_upstream"
    fi
    for file in "${vmbus_channel_files[@]}"; do
        if [ ! -f "$channel_path/$file" ]; then
            LogErr "$channel_path/$file does not exist"
            test_failed="true"
        fi
        if ! cat "$channel_path/$file" > /dev/null; then
            LogErr "Cannot read file: $channel_path/$file"
            test_failed="true"
        fi
    done
fi

if [ -z "$test_failed" ]; then
    LogMsg "Driver file structure is Ok."

    # Check that in_* & out_* files are equal when read together
    # in_intr_mask
    # in_read_bytes_avail
    # in_read_index
    # in_write_bytes_avail
    # in_write_index

    inFiles="$(cat in*)"
    outFiles="$(cat out*)"
    if [ "$inFiles" == "$outFiles" ]; then
        LogMsg "in_* files are equal to out_* files"
    else
        LogErr "in_* files are equal to out_* files"
    fi

    if [ -d "$channel_path" ]; then
        # check events and interrupts increase per channel as we read the files
        old_interrupts=$(cat $channel_path/interrupts)
        old_events=$(cat $channel_path/events)
        for iterator in {1..5}; do
            sleep 2
            interrupts=$(cat $channel_path/interrupts)
            events=$(cat $channel_path/events)
            if [ $interrupts -gt $old_interrupts ] && [ $events -gt $old_events ]; then
                LogMsg "Interrupts and events increased on $iterator try."
            else
                LogErr "Interrupts and events did not increase on try $iterator"
            fi
            old_interrupts=$interrupts
            old_events=$events
        done
    fi
fi

if [ ! -z "$test_failed" ]; then
    LogErr "All Heartbeat driver files: $(ls -alR)"
    LogErr "All Heartbeat sys files content: $(cat $sys_path/*)"
    LogErr "All Heartbeat channel files content: $(cat $sys_path/channels/*/*)"
    SetTestStateFailed
else
    SetTestStateCompleted
fi
exit 0
