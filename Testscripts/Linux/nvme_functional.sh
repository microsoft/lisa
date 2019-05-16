#!/bin/bash

# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
# Description:
# Functional NVME test script. For each NVME device it does the following:
# - Creates a partition, filesystem & then mounts it
# - Creates 2 files on the partition
# - Unmount & mount the partition.
# - Checks the 2 files
# - Compares the number of errors from nvme-cli before/after testing
######################################################################

. utils.sh || {
    echo "ERROR: unable to source utils.sh!"
    echo "TestAborted" > state.txt
    exit 0
}
UtilsInit

# Install nvme-cli tool
update_repos
install_nvme_cli

# Count NVME namespaces
namespace_count=$(ls -l /dev | grep -w nvme[0-9]n[0-9]$ | awk '{print $10}' | wc -l)
if [ "$namespace_count" -eq "0" ]; then
    LogErr "No NVME namespaces detected inside the VM"
    SetTestStateFailed
    exit 0
fi

# Check namespaces in nvme cli
namespace_list=$(ls -l /dev | grep -w nvme[0-9]n[0-9]$ | awk '{print $10}')
for namespace in ${namespace_list}; do
    # Count error from nvme error-log before any operations
    initial_error_count=$(nvme error-log /dev/"$namespace" | grep error_count | awk '{sum+=$3} END {print sum}')

    # Remove previous partitions or RAID config
    umount "$namespace"
    (echo d; echo w) | fdisk /dev/"$namespace"
    mdvol=$(cat /proc/mdstat | grep active | awk {'print $1'})
    if [ -n "$mdvol" ]; then
        umount /dev/"${mdvol}"
        mdadm --stop /dev/"${mdvol}"
        mdadm --remove /dev/"${mdvol}"
        mdadm --zero-superblock /dev/nvme[0-9]n[0-9]p[0-9]
    fi
    sleep 1
    # Partition disk
    (echo n; echo p; echo 1; echo ; echo; echo ; echo w) | fdisk /dev/"$namespace"
    if [ $? -ne 0 ]; then
        LogErr "Failed to partition ${namespace} disk"
        SetTestStateFailed
        exit 0
    fi
    sleep 1
    # Create fileSystem
    echo "y" | mkfs.ext4 /dev/"$namespace"p1
    if [ $? -ne 0 ]; then
        LogErr "Failed to create ext4 filesystem on ${namespace}"
        SetTestStateFailed
        exit 0
    fi
    # Mount the disk
    mkdir "$namespace"
    mount /dev/"$namespace"p1 "$namespace"
    if [ $? -ne 0 ]; then
        LogErr "Failed to mount ${namespace}p1"
        SetTestStateFailed
        exit 0
    fi
    LogMsg "Successfully created partition on ${namespace} & mounted it!"

    # Create files on the partition
    echo "TestContent" > "$namespace"/testfile.txt
    dd if=/dev/zero of="$namespace"/data bs=10M count=100
    if [ $? -ne 0 ]; then
        LogErr "Failed to create 1GB file on ${namespace}"
        SetTestStateFailed
        exit 0
    fi
    initial_md5=$(md5sum "$namespace"/data | awk '{print $1}')

    # Unmount the partition
    umount "$namespace"
    if [ $? -ne 0 ]; then
        LogErr "Failed to unmount ${namespace}"
        SetTestStateFailed
        exit 0
    fi
    # Mount the partition again
    sleep 5
    mount /dev/"$namespace"p1 "$namespace"
    if [ $? -ne 0 ]; then
        LogErr "Failed to mount ${namespace}p1"
        SetTestStateFailed
        exit 0
    fi

    # Check the previously created files
    cat "$namespace"/testfile.txt | grep "TestContent"
    if [ $? -ne 0 ]; then
        LogErr "The previously created file doesn't have the expected content!"
        SetTestStateFailed
        exit 0
    fi
    final_md5=$(md5sum "$namespace"/data | awk '{print $1}')
    if [ "$initial_md5" != "$final_md5" ]; then
        LogErr "md5sum doesn't match after unmounting and mounting ${namespace}!"
        SetTestStateFailed
        exit 0
    fi
    # Count errors again from nvme-cli
    final_error_count=$(nvme error-log /dev/"$namespace" | grep error_count | awk '{sum+=$3} END {print sum}')
    if [ "$initial_error_count" != "$final_error_count" ]; then
        LogErr "nvme error-log shows that error count has changed on ${namespace}!"
        LogErr "Initial error count: ${initial_error_count}"
        LogErr "Final error count: ${final_error_count}"
        SetTestStateFailed
        exit 0
    fi
    umount "$namespace"
    UpdateSummary "All the operations on ${namespace} worked as expected!"
done

# All the operations succeeded and the test is complete
SetTestStateCompleted
exit 0