#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
#
# Sample script to run sysbench.
# In this script, we want to bench-mark device IO performance on a mounted folder.
# You can adapt this script to other situations easily like for stripe disks as RAID0.
# The only thing to keep in mind is that each different configuration you're testing
# must log its output to a different directory.
#

HOMEDIR="/home/lisa/"
LogMsg()
{
	echo "[$(date +"%x %r %Z")] ${1}"
	echo "[$(date +"%x %r %Z")] ${1}" >> "${HOMEDIR}/runlog.txt"
}
LogMsg "Sleeping 10 seconds.."
sleep 10

#CONSTANTS_FILE="$HOMEDIR/constants.sh"
UTIL_FILE="$HOMEDIR/utils.sh"
STATE_FILE="$HOMEDIR/state.txt"
ICA_TESTRUNNING="TestRunning"      # The test is running
ICA_TESTCOMPLETED="TestCompleted"  # The test completed successfully
ICA_TESTABORTED="TestAborted"      # Error during the setup of the test
ICA_TESTFAILED="TestFailed"        # Error occurred during the test
touch $STATE_FILE

. ${UTIL_FILE} || {
	errMsg="Error: missing ${UTIL_FILE} file"
	LogMsg "${errMsg}" 
	UpdateTestState $ICA_TESTABORTED
	exit 10
}

UpdateTestState()
{
	echo "${1}" > ${HOMEDIR}/state.txt
}

CreateRAID0()
{	
	
	disks=$(ls -l /dev | grep sd[c-z]$ | awk '{print $10}')
	#disks=(`fdisk -l | grep 'Disk.*/dev/sd[a-z]' |awk  '{print $2}' | sed s/://| sort| grep -v "/dev/sd[ab]$" `)
	UpdateTestState ICA_TESTRUNNING
	LogMsg "INFO: Check and remove RAID first"
	mdvol=$(cat /proc/mdstat | grep "active raid" | awk {'print $1'})
	if [ -n "$mdvol" ]; then
		echo "/dev/${mdvol} already exist...removing first"
		umount /dev/${mdvol}
		mdadm --stop /dev/${mdvol}
		mdadm --remove /dev/${mdvol}
		mdadm --zero-superblock /dev/sd[c-z][1-5]
	fi
	
	LogMsg "INFO: Creating Partitions"
	count=0
	for disk in ${disks}
	do		
		echo "formatting disk /dev/${disk}"
		(echo d; echo n; echo p; echo 1; echo; echo; echo t; echo fd; echo w;) | fdisk /dev/${disk}
		count=$(( $count + 1 ))
		sleep 1
	done
	LogMsg "INFO: Creating RAID of ${count} devices."
	sleep 1
	mdadm --create ${mdVolume} --level 0 --raid-devices ${count} /dev/sd[c-z][1-5]
	sleep 1
	time mkfs -t $1 -F ${mdVolume}
	mkdir ${mountDir}
	sleep 1
	mount -o nobarrier ${mdVolume} ${mountDir}
	if [ $? -ne 0 ]; then
		LogMsg "Error: Unable to create raid"
		UpdateTestState ICA_TESTABORTED
		exit 1
	else
		LogMsg "${mdVolume} mounted to ${mountDir} successfully."
	fi
	
	LogMsg "INFO: adding fstab entry"
	echo "${mdVolume}	${mountDir}	ext4,nobarrier	defaults	0 0" >> /etc/fstab
	LogMsg "INFO: Successfuly Added fstab entry"
	UpdateTestState ICA_TESTCOMPLETED
	
}

mdVolume="/dev/md0"
mountDir="/data"
cd ${HOMEDIR}

install_fio
CreateRAID0 ext4
