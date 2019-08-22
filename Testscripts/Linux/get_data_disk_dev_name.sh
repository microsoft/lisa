#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

# Source utils.sh
. utils.sh || {
    echo "Error: unable to source utils.sh!"
    echo "TestAborted" > state.txt
    exit 0
}

lsblk -V >/dev/null 2>&1
if [ $? -ne 0 ]; then
    update_repos >/dev/null 2>&1
    install_package "util-linux" >/dev/null 2>&1
fi

# Get the OS disk
os_disk=$(get_OSdisk)

for dev in /dev/sd*[^0-9]; do
    # Skip the OS disk
    if [ $dev == "/dev/$os_disk" ]; then
        continue
    fi
    # Skip the resource disk based on the disk size.
    # It's not an accurate method when size of other data disks is 1GB,
    # but it does not effect the test because the resource disk is also a data disk.
    lsblk  --output SIZE -n -d $dev 2> /dev/null | grep -i "1G" > /dev/null
    if [ 0 -eq $? ]; then
        # Set a default name in case size of all data disks is 1GB
        deviceName=$dev
        continue
    fi
    deviceName=$dev
    break
done

echo "$deviceName"
exit 0