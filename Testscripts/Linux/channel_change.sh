#!/bin/bash
#
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
# This script sets up CPU offline feature with the vmbus interrupt channel re-assignment, which would be available in 5.8+
########################################################################################################
# Source utils.sh
. utils.sh || {
	echo "Error: unable to source utils.sh!"
	echo "TestAborted" > state.txt
	exit 0
}
# Source constants file and initialize most common variables
UtilsInit

failed_count=0

# Get distro information
GetDistro

function Main() {
	# #######################################################################################
	# Read VMBUS ID and store vmbus ids in the array
	# Change the cpu_id from non-zero to 0 in order to set cpu offline.
	# If successful, all cpu_ids in lsvmbus output should be 0 of each channel, and generate
	# the list of idle cpus

	basedir=$(pwd)
	# restore the original vmbus and cpu id restored in OriginalSource file.
	OriginalSource=vmbus_cpu.original
	if [ -f $OriginalSource ]; then
		rm -f $OriginalSource
	fi
	touch $OriginalSource
	LogMsg "Change all vmbus channels' cpu id to 0, if non-zero"
	for _device in /sys/bus/vmbus/devices/*
	do
		echo $_device >> $OriginalSource
		# Need to access the copy of channel_vp_mapping to avoid race condition.
		cp $_device/channel_vp_mapping .
		# read channel_vp_mapping file of each device
		while IFS=: read _vmbus_ch _cpu
		do
			LogMsg "vmbus: $_vmbus_ch,		cpu id: $_cpu"
			echo "$_vmbus_ch:$_cpu" >> $OriginalSource
			if [ $_cpu != 0 ]; then
				idle_cpus+=($_cpu)

				# Now reset this cpu id to 0.
				LogMsg "Set the vmbus channel $_vmbus_ch's cpu to the default cpu, 0"
				echo 0 > $_device/channels/$_vmbus_ch/cpu
				sleep 1
				# validate the change of that cpu id
				_cpu_id=$(cat $_device/channels/$_vmbus_ch/cpu)
				if [ $_cpu_id = 0 ]; then
					LogMsg "Successfully set the vmbus channel $_vmbus_ch's cpu to 0"
				else
					LogErr "Failed to set the vmbus channel $_vmbus_ch's cpu to 0. Expected 0, but found $_cpu_id"
					failed_count=$((failed_count+1))
				fi
			fi
			sleep 1
		done < channel_vp_mapping
	done

	# #######################################################################################
	# The previous step sets all channels' cpu to 0, so the rest of non-zero cpu can be offline
	LogMsg "Change all cpu state from online to offline, and vice versa."
	cpu_index=$(nproc)
	id=1
	while [[ $id -lt $cpu_index ]] ; do
		state=$(cat /sys/devices/system/cpu/cpu$id/online)
		if [ $state = 1 ]; then
			LogMsg "Verified the current cpu $id online"
			# Set cpu to offline
			echo 0 > /sys/devices/system/cpu/cpu$id/online
			sleep 1
			LogMsg "Set the cpu $id offline"
			post_state=$(cat /sys/devices/system/cpu/cpu$id/online)
			if [ $post_state = 0 ]; then
				LogMsg "Successfully set the cpu $id offline"
				# Change back to online
				echo 1 > /sys/devices/system/cpu/cpu$id/online
				sleep 1
				LogMsg "Set the cpu $id online"
				post_state=$(cat /sys/devices/system/cpu/cpu$id/online)
				if [ $post_state = 1 ]; then
					LogMsg "Successfully set the cpu $id online"
					sleep 1
				else
					LogErr "Failed to set the cpu $id online. Expected 1, found $post_state"
					failed_count=$((failed_count+1))
				fi
			else
				LogErr "Failed to set the cpu $id offline. Expected 0, found $post_state"
				failed_count=$((failed_count+1))
			fi
		else
			LogErr "Found the currect cpu $id was not online. Expected 1, found $state"
			failed_count=$((failed_count+1))
		fi
		((id++))
	done
	LogMsg "Completed the non-assigned cpu state change"
	if [ $failed_count != 0 ]; then
		LogErr "Failed case counts: $failed_count"
		SetTestStateFailed
	fi
	# ########################################################################
	# The previous step sets all cpus to online state, but all channels use cpu 0
	# Assign a random CPU id to the vmbus channel
	# Assign the original CPU id to the vmbus channel
	# Now each vmbus's cpu id is 0.

	# Find the max CPU core counts
	max_cpu=$(nproc)
	# Read the original vmbus and cpu information from the previous capture.
	LogMsg "Assign a random cpu id and, then the original cpu id to the vmbus channel"
	while IFS= read line
	do
		if [[ $line == *"/sys/bus"* ]]; then
			_path=$line
		else
			_vmbus_ch=$(echo $line | cut -d ":" -f 1)
			_cpu=$(echo $line | cut -d ":" -f 2)
			if [ $_cpu != 0 ]; then
				LogMsg "Testing for sysfs: $_path, vmbus channel: $_vmbus_ch, cpu id: $_cpu"
				# Change to random number
				cpu_rdn=$(($RANDOM % $max_cpu))
				echo $cpu_rdn > $_path/channels/$_vmbus_ch/cpu
				# Read back new cpu id
				_cpu_id=$(cat $_path/channels/$_vmbus_ch/cpu)
				if [ $_cpu_id = $cpu_rdn ]; then
					LogMsg "Verified the random number assigned to cpu successfully"
				else
					LogErr "Failed to verify random number assignment to the cpu id. Expected $cpu_rdn, found $_cpu_id"
					failed_count=$((failed_count+1))
				fi
				# Change to the original cpu id _cpu
				echo $_cpu > $_path/channels/$_vmbus_ch/cpu
				# Read back new cpu id
				_cpu_id=$(cat $_path/channels/$_vmbus_ch/cpu)
				if [ $_cpu = $_cpu_id ]; then
					LogMsg "Verified the original number assigned to cpu successfully"
				else
					LogErr "Failed to verify the original number assignment to the cpu id. Expected $_cpu, found $_cpu_id"
					failed_count=$((failed_count+1))
				fi
			fi
		fi
	done < $OriginalSource
	echo "job_completed=0" >> $basedir/constants.sh
	LogMsg "Main function job completed"
	if [ $failed_count == 0 ]; then
		SetTestStateCompleted
	else
		LogErr "Failed case counts: $failed_count"
		SetTestStateFailed
	fi
}

# main body
Main
exit 0