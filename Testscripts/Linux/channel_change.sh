#!/bin/bash
#
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
# This script will set up CPU offline feature with vmbus interrupt channel re-assignment.
# This feature will be enabled the kernel version 5.7+
# Select a CPU number where does not associate to vmbus channels; /sys/bus/vmbus/devices/<device ID>/channels/<channel ID>/cpu.
# Set 1 to online file, echo 1 > /sys/devices/system/cpu/cpu<number>/online
# Verify the dmesg log like ‘smpboot: Booting Node xx Processor x APIC 0xXX’
# Set 0 to online file, echo 0 > /sys/devices/system/cpu/cpu<number>/online
# Verify the dmesg log like ‘smpboot: CPU x is now offline’
# Select a CPU number where associates to vmbus channels.
# Set 1 to online file, echo 1 > /sys/devices/system/cpu/cpu<number>/online
# Verify the command error: Device or resource busy
# Set 0 to online file, echo 0 > /sys/devices/system/cpu/cpu<number>/online
# Verify the command error: Device or resource busy
########################################################################################################
# Source utils.sh
. utils.sh || {
	echo "Error: unable to source utils.sh!"
	echo "TestAborted" > state.txt
	exit 0
}
# Source constants file and initialize most common variables
UtilsInit

# Constants/Globals
# Get distro information
GetDistro

# Global variables
lsvmbus_output_location=/tmp/lsvmbus.output
vmbus_id=()
idle_cpus=()
prefix1="Rel_ID="
suffix1=","
prefix2="target_cpu="

function reset_cpu_id() {
# Read VMBUS ID and store vmbus ids in the array
# Change the cpu_id from non-zero to 0 in order to set cpu offline.
# If successful, all cpu_ids in lsvmbus output should be 0 per channel, and generate
# the list of idle cpus

	lsvmbus_output_location="/tmp/lsvmbus.output"
	idx=0
	cpu_idx=0
	while IFS=' ' read -a line
	do
		if [[ ${line[0]} == "VMBUS" && ${line[1]} == "ID" ]]; then
			vmbus_id[$idx]=${line[2]%?}
			LogMsg "Found new VMBUS ID --> ${vmbus_id[$idx]}"

			read -a line
			# Ignored Device Id

			read -a line
			if [[ ${line[0]} =~ "Sysfs" && ${line[1]} == "path:" ]]; then
				sysfs_path=${line[2]}
				LogMsg "Found new sysfs --> $sysfs_path"

				# Read Rel_ID and target_cpu lines
				read -a line
				while [[ $line != '' ]]
				do
					rel_id=${line[0]#"$prefix1"}
					rel_id=${rel_id%"$suffix1"}
					LogMsg "Found Rel_ID: $rel_id"
					cpu_id=${line[1]#"$prefix2"}
					LogMsg "Found target_cpu: $cpu_id"
					if [[ $cpu_id != "0" ]]; then
						_cpu_id=$(cat $sysfs_path/channels/$rel_id/cpu)
						idle_cpus+=($_cpu_id)
						LogMsg "Found the cpu id, $_cpu_id from the channel $rel_id. Will set 0, the default cpu id, to this cpu"
						echo 0 > $sysfs_path/channels/$rel_id/cpu
						sleep 1
						# validate the change of that cpu id
						_cpu_id=$(cat $sysfs_path/channels/$rel_id/cpu)
						if [[ $_cpu_id == "0" ]]; then
							LogMsg "Successfully changed the cpu id of the channel $rel_id from ${idle_cpus[$cpu_idx]} to 0"
							cpu_idx=$((cpu_idx+1))
						else
							LogErr "Failed to change the cpu id of the channel $rel_id from ${idle_cpus[$cpu_idx]} to 0. Expected 0, but found $_cpu_id"
						fi
					fi
					read -a line
				done
				#LogMsg "Found vmbus channel and its target cpus: ${temp[@]}, ${!temp[@]}"
			else
				LogErr "Supposed to read Sysfs path, but found ${line[@]}"
			fi
			idx=$((idx+1))
		else
			LogErr "Supposed to read VMBUS ID line, but found ${line[@]}"
		fi
		LogMsg ""
	done < "$lsvmbus_output_location"

	LogMsg "VMBUS scanning result: ${vmbus_id[@]}"
	return
}

function Main() {
	# Collect the vmbus and cpu id information from the system, and store in /tmp/lsvmbus.output
	basedir=$(pwd)
	lsvmbus
	if [ $? != 0 ]; then
		if [ -f $basedir/linux/tools/hv/lsvmbus ]; then
			chmod +x $basedir/linux/tools/hv/lsvmbus
			$basedir/linux/tools/hv/lsvmbus -vv > $lsvmbus_output_location
		else
			LogErr "File, lsvmbus, not found in the system. Aborted the execution."
			SetTestStateAborted
			exit 0
		fi
	else
		lsvmbus -vv > $lsvmbus_output_location
	fi
	LogMsg "Successfully recorded lsvmbus output in $lsvmbus_output_location"

	# Before chaning cpu id to 0, reset all cpu ids of each vmbus channel.
	LogMsg "Resetting CPU ID if non-zero"
	reset_cpu_id

	# Select a CPU number where does not associate to vmbus channels from idle_cpus array
	for id in ${idle_cpus[@]}; do
		state=$(cat /sys/devices/system/cpu/cpu$id/online)
		if [[ $state == "1" ]]; then
			LogMsg "Verified the current cpu $id is online"
			dmesg > /tmp/pre-stage.log
			LogMsg "Took a snapshot of dmesg to /tmp/pre-stage.log"
			# set cpu to offline
			echo 0 > /sys/devices/system/cpu/cpu$id/online
			LogMsg "Changed the cpu $id state to offline"
			sleep 1
			post_state=$(cat /sys/devices/system/cpu/cpu$id/online)
			if [[ $post_state == "0" ]]; then
				LogMsg "Successfully verified to change the cpu $id state to offline"
				sleep 1
				dmesg > /tmp/post-stage.log
				diff_val=$(diff /tmp/pre-stage.log /tmp/post-stage.log)
				if [[ $diff_val == *"CPU $id is now offline"* ]]; then
					LogMsg "Successfully found dmesg log per cpu offline state change"
					# Change back to online
					echo 1 > /sys/devices/system/cpu/cpu$id/online
					LogMsg "Changed the cpu $id state to online"
					sleep 1
					post_state=$(cat /sys/devices/system/cpu/cpu$id/online)
					if [[ $post_state == "1" ]]; then
						LogMsg "Successfully verified to change back the cpu $id state to online"
						sleep 1
						dmesg > /tmp/post-stage2.log
						diff_val2=$(diff /tmp/post-stage.log /tmp/post-stage2.log)
						if [[ $diff_val2 == *"smpboot: Booting Node"* ]]; then
							LogMsg "Successfully found dmesg log per cpu online state change"
						else
							LogErr "Failed to verify cpu online state change. Expected smpboot: Booting Node, but found $diff_val2"
						fi
					else
						LogErr "Failed to change back cpu $id to onlone"
					fi
				else
					LogErr "Failed to find the expected dmesg. Expected CPU $id is now offline, but found $diff_val"
				fi
			else
				LogErr "Failed to change the cpu $id state to offline. Expected 0, but found $post_state"
			fi
		else
			LogErr "Found the currect cpu $id is not online. Expected 1 but found $state"
		fi
		LogMsg ""
	done

	echo "job_completed=0" >> $basedir/constants.sh
	LogMsg "Main function job completed"
}

# main body
Main
SetTestStateCompleted
exit 0