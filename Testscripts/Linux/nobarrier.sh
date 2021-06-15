#!/bin/bash
#######################################################################
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
# nobarrier.sh
# Description:
#    Download and run No barrier Disk Test.
# Supported Distros:
#    Ubuntu, SUSE, RedHat, CentOS
#######################################################################
CONSTANTS_FILE="./constants.sh"
. ${CONSTANTS_FILE} || {
	echo "ERROR: unable to source constants.sh!"
	echo "TestAborted" > state.txt
	exit 1
}
UTIL_FILE="./utils.sh"
. ${UTIL_FILE} || {
	echo "ERROR: unable to source utils.sh!"
	echo "TestAborted" > state.txt
	exit 2
}
# Source constants file and initialize most common variables
UtilsInit

# Create RAID using unused data disks attached to the VM.
function create_raid_and_mount() {
		local deviceName="/dev/md1"
		local mountdir=/data-dir
		local format="ext4"
		local mount_option=""
		if [[ ! -z "$1" ]];then
			deviceName=$1
		fi
		if [[ ! -z "$2" ]];then
			mountdir=$2
		fi
		if [[ ! -z "$3" ]];then
			format=$3
		fi
		if [[ ! -z "$4" ]];then
			mount_option=$4
		fi

	local uuid=""
	local list=""

	LogMsg "IO test setup started.."
	list=$(get_AvailableDisks)

	lsblk
	install_package mdadm
	create_raid0 "$list" "$deviceName"

	time mkfs -t $format $deviceName
	check_exit_status "$deviceName Raid format"

	mkdir $mountdir
	uuid=$(blkid $deviceName| sed "s/.*UUID=\"//"| sed "s/\".*\"//")
	cp -f /etc/fstab /etc/fstab_raid
	echo "UUID=$uuid $mountdir $format defaults 0 2" >> /etc/fstab
	if [ -z "$mount_option" ]
	then
		mount $deviceName $mountdir
	else
		mount -o $mount_option $deviceName $mountdir
	fi
	check_exit_status "RAID ($deviceName) mount on $mountdir as $format"
}

#Install required packages for raid
packages=("gcc" "git" "tar" "wget" "dos2unix" "mdadm")
case "$DISTRO_NAME" in
	oracle|rhel|centos|almalinux)
		install_epel
		;;
	ubuntu|debian)
		update_repos
		;;
	suse|opensuse|sles)
		add_sles_network_utilities_repo
		;;
	coreos|clear-linux-os|mariner)
		;;
	*)
		LogErr "Unknown distribution"
		SetTestStateAborted
		exit 1
esac
install_package "${packages[@]}"
# Raid Creation
create_raid_and_mount "$deviceName" "$mountDir" "$diskformat" "$mount_option"
mount -l | grep "$mountDir"
if [ $? -ne 0 ]; then
	LogErr "Error: ${deviceName} not mounted with ${mount_option}"
	SetTestStateFailed
else
	LogMsg "${deviceName} mounted with ${mount_option}"
	SetTestStateCompleted
	LogMsg "Umount $mountDir and stop $deviceName"
	umount "$mountDir"
	mdadm --stop "$deviceName"
	[ -f /etc/fstab_raid ] && cp -f /etc/fstab_raid /etc/fstab
fi
