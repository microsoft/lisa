#!/bin/bash
#
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
# This script sets up CPU offline feature with the vmbus interrupt channel re-assignment, which would be available in 5.8+
# vmbus channel of synthetic network adapter is changed by ethtool with offlined cpu, and verifies the result.
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
	syn_net_adpt=""

	command -v ethtool > /dev/null || install_package ethtool

	LogMsg "Change all vmbus channels' cpu id to 0, if non-zero"
	for _device in /sys/bus/vmbus/devices/*
	do
		# Get Class ID and determine if this device is Synthetic Network Adapter.
		# https://github.com/torvalds/linux/blob/master/tools/hv/lsvmbus#L34
		# {f8615163-df3e-46c5-913f-f2d2f965ed0e}
		# The copied file is used in next steps.
		cid=$(cat $_device/class_id)
		if [[ $cid == "{f8615163-df3e-46c5-913f-f2d2f965ed0e}" ]]; then
			syn_net_adpt=$_device
		fi

		# Need to access the copy of channel_vp_mapping to avoid race condition.
		cp $_device/channel_vp_mapping .
		# read channel_vp_mapping file of each device
		while IFS=: read _vmbus_ch _cpu
		do
			LogMsg "vmbus: $_vmbus_ch,		cpu id: $_cpu"
			if [ $_cpu != 0 ]; then
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
	LogMsg "Set all online idles cpus to offline."
	cpu_index=$(nproc)
	id=1
	while [[ $id -lt $cpu_index ]] ; do
		state=$(cat /sys/devices/system/cpu/cpu$id/online)
		if [ $state = 1 ]; then
			# Set cpu to offline
			echo 0 > /sys/devices/system/cpu/cpu$id/online
			sleep 1
			LogMsg "Set the cpu $id offline"
			post_state=$(cat /sys/devices/system/cpu/cpu$id/online)
			if [ $post_state = 0 ]; then
				LogMsg "Successfully verified the cpu $id offline"
			else
				LogErr "Failed to verify the cpu $id state. Expected 0, found $post_state"
				failed_count=$((failed_count+1))
			fi
		fi
		((id++))
	done

	if [ $failed_count != 0 ]; then
		LogErr "Failed case counts: $failed_count"
		SetTestStateFailed
		exit 0
	fi
	# ########################################################################
	# The previous steps set all cpus to offline, but all channels use cpu 0
	# By using ethtool command, it sets new channels
	# Verify if any offline cpu is assigned to new channels or not.
	# Verify cpu should stay offline state.
	LogMsg "Change vmbus channel numbers by ethtool command"
	_ch_counts=$(ethtool -l eth0 | grep -i combined | tail -1 | cut -d ':' -f 2 | sed -e 's/^[[:space:]]*//')
	LogMsg "Current channel counts: $_ch_counts"

	max_cpu=$(nproc)

	# Set the random channel numbers to network device.
	# max channel number is 64.
	# Source: https://github.com/torvalds/linux/blob/master/drivers/net/hyperv/hyperv_net.h#L842
	_new_counts=$(($RANDOM % $max_cpu))
	((_new_counts=_new_counts+1))

	ethtool -L eth0 combined $_new_counts
	if [ $? != 0 ]; then
		LogErr "Failed to execute channel number change by ethtool, $?"
		failed_count=$((failed_count+1))
	else
		sleep 1
		LogMsg "Changed the channel numbers to $_new_counts"

		if [ ! -d "$syn_net_adpt" ]; then
			LogErr "Can not find the synthetic network adapter of vmbus sysfs path. The test failed."
			failed_count=$((failed_count+1))
		else
			cp $syn_net_adpt/channel_vp_mapping new_channel_vp_mapping

			while IFS=: read v c; do
				LogMsg "Found vmbus channel: $v,		cpu: $c"
				# Run test against all except cpu0.
				if [ $c != 0 ]; then
					# CPU is offline
					_state=$(cat /sys/devices/system/cpu/cpu$c/online)
					if [ $_state = 0 ]; then
						LogErr "Found the offlined cpu, $c is assigned to channel interrupt, $v. This should be 1, if cpu is used in channel interrupt."
						failed_count=$((failed_count+1))
					else
						LogMsg "Verified the channel interrupt, $v is assigned to online cpu, $c"
					fi
				fi
			done < new_channel_vp_mapping
		fi
	fi
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
