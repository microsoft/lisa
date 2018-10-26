#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

######################################################################################
# STOR_VHDXResize_GrowFSAfterResize.sh
# Description:
#  This script will verify if you can resize the filesystem on a resized VHDx file.
#  The test performs the following steps:
#  On first run:
#    1. Create partition
#    2. Format partition
#    4. Mount the partition
#    5. Read/Write mount point
#    6. Unmount partition
#  On second run (after vhdx is resized):
#    4. Expand partition
#    5. Check filesystem
#    6. Resize filesystem
#    4. Mount the partition
#    5. Read/Write mount point
#    6. Unmount partition
#    7. Delete partition
######################################################################################

# Source utils.sh
. utils.sh || {
	echo "Error: unable to source utils.sh!"
	echo "TestAborted" >state.txt
	exit 1
}

# Source constants file and initialize most common variables
UtilsInit

if [ "${deviceName:-UNDEFINED}" = "UNDEFINED" ]; then
	LogErr "Parameter deviceName is not defined in constants file."
	SetTestStateAborted
	exit 1
fi
mntDir="/mnt"

# Verify if guest detects the drive
if [ ! -e "$deviceName" ]; then
	LogErr "The Linux guest cannot detect the drive"
	SetTestStateAborted
	exit 1
fi
LogMsg "The Linux guest detected the drive"

if ! [ "$rerun" = "yes" ]; then
	LogMsg "Info: Start testing filesystem: $fs"

	# Create the partition
	LogMsg "Info: Creating the partition on initial size of VHD."
	(echo n; echo p; echo 1; echo ; echo ;echo w) | fdisk "$deviceName" 2> /dev/null
	check_exit_status "Create partition" "LogMsg"

	partprobe
	sync

	# Verify if filesystem exist and then format the partition
	command -v mkfs.$fs
	if [ $? -ne 0 ]; then
		LogErr "File-system tools for $fs not present. Skipping filesystem $fs."
	else
		#Use -f option for xfs filesystem, but ignore parameter for other filesystems
		option=""
		if [ "$fs" = "xfs" ]; then
			option="-f"
		fi
		mkfs -t $fs $option "$deviceName"1
		check_exit_status "Format partition with $fs" "LogMsg"
	fi

	# Mount partition
	if [ ! -e "$mntDir" ]; then
		mkdir $mntDir
	check_exit_status "Create mount point" "LogMsg"
	fi

	mount "$deviceName"1 $mntDir
	check_exit_status "Mount partition" "LogMsg"

	mount | grep "$deviceName"1

	# Read/Write mount point
	./STOR_VHDXResize_ReadWrite.sh

	# Umount partition
	umount $mntDir
	check_exit_status "Unmount partition" "LogMsg"
else
	LogMsg "Continue testing $fs."
	LogMsg "Expand partition to the new size"

	# Expand partition to the new size of disk
	(echo d; echo w) | fdisk "$deviceName" 2> /dev/null
	partprobe
	(echo n; echo p; echo 1; echo ; echo ;echo w) | fdisk "$deviceName" 2> /dev/null
	check_exit_status "Expand partition" "LogMsg"

	partprobe
	sync

	# Checking filesystem
	# Because e2fsck and resize2fs only work for ext filesystems
	# we need to skip xfs for now
	if [ ! "$fs" = "xfs" ]; then
		e2fsck -y -v -f "$deviceName"1
	check_exit_status "Check filesystem" "LogMsg"
	fi

	# Resizing the filesystem
	if [ ! "$fs" = "xfs" ]; then
		resize2fs "$deviceName"1
	check_exit_status "Resize filesystem" "LogMsg"
	fi

	# Mount partition
	if [ ! -e "$mntDir" ]; then
		mkdir $mntDir
		check_exit_status "Create mount point" "LogMsg"
	fi

	mount "$deviceName"1 $mntDir
	check_exit_status "Mount partition" "LogMsg"
	mount | grep "$deviceName"1

	# If the partition was successfully mounted we can use xfs_growsfs to
	# check the XFS filesystem also
	if [ "$fs" = "xfs" ]; then
		xfs_growfs -d $mntDir
		check_exit_status "Resize filesystem $fs" "LogMsg"
	fi

	# Read/Write mount point
	./STOR_VHDXResize_ReadWrite.sh

	# Umount partition
	umount $mntDir
	check_exit_status "Unmount partition" "LogMsg"

	# Delete partition
	(echo d; echo w) | fdisk "$deviceName"
	partprobe
	lsblk | grep ${mntDir#"/dev/"}"1"
	check_exit_status "Delete partition" "LogMsg"
	partprobe
fi

SetTestStateCompleted
