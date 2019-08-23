#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

# Description:
#    This script will verify that the first logical sector size
#    is a multiple of 8 and logical sector and pyshical size
# Steps:
#    1. fdisk with {n,p,w}, fdisk -lu (by default display sections units )
#    2. Verify the first sector of the disk is a multiple of 8
#    3. Verify the logical sector size (512) and physical size (4096/4k)

# Source utils.sh
. utils.sh || {
    LogErr "unable to source utils.sh!"
    SetTestStateAborted
    exit 0
}

UtilsInit
# Need to add one disk before test
drive_name=$(bash get_data_disk_dev_name.sh)
# Check if parted is installed. If no, install it.
parted --help > /dev/null 2>&1
if [ $? -ne 0 ] ; then
    update_repos
    install_package parted
fi

# Create partition
parted $drive_name mklabel msdos
parted $drive_name mkpart primary 0% 100%
fdisk_cmd=$(fdisk -lu $drive_name)
test_disk=${drive_name}1
start_sector=$(echo ${fdisk_cmd} | grep -o ${test_disk}.* | awk '{print $2}')
logical_sector_size=$(echo ${fdisk_cmd} | grep -o 'logical/physical).*' | awk '{print $2}')
physical_sector_size=$(echo ${fdisk_cmd} | grep -o 'logical/physical).*' | awk '{print $5}')

if [ $(($start_sector%8)) -eq 0 ]; then
    LogMsg "Check the first sector size on $drive_name disk $start_sector is a multiple of 8: Success"
else
    LogErr "Check the first sector size on $drive_name disk $start_sector is a multiple of 8 : Failed"
    SetTestStateAborted
    exit 0
fi

#
# check logical sector size is 512 and physical sector is 4096
# 4k alignment only needs to test in 512 sector
#
if [[ $logical_sector_size = 512 && $physical_sector_size = 4096 ]]; then
    LogMsg "Check logical and physical sector size on disk $drive_name: Success"
else
    LogErr "Check logical and physical sector size on disk  $drive_name: Failed"
    SetTestStateAborted
    exit 0
fi

SetTestStateCompleted
exit 0
