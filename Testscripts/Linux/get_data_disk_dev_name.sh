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

    deviceName=$dev
    break
done

echo "$deviceName"
exit 0