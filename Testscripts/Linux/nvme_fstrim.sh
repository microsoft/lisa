#!/bin/bash

# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
# Description:
# Fstrim NVME test script. For each NVME device it does the following:
# - Partition nvme0n1 (a single partition). Create xfs filesystem and mount the partition.
# - fstrim mountPoint  -v => check how much is trimmed. 1.8 TiB should be the output of fstrim
#  (e.g. nvme0n1: 1.8 TiB (1919444512768 bytes) trimmed)
# - Create a 300 gb file using "dd if=/dev/zero mountPoint/data bs=1G count=300"
# - fstrim mountPoint  -v => 1.5 TiB should be the output of fstrim
#  (e.g. nvme0n1: 1.5 TiB (1604871708672 bytes) trimmed
# - Remove file
# - fstrim mountPoint -v => 1.8 TiB should be trimmed again.
#If every trim size check is as expected, test is successful.
#########################################################################

. utils.sh || {
    echo "ERROR: unable to source utils.sh!"
    echo "TestAborted" > state.txt
    exit 0
}
UtilsInit
Run_Fstrim() {
    # Install nvme-cli tool and parted
    update_repos
    install_package "nvme-cli"
    # Count NVME namespaces
    namespace_count=$(echo /dev/nvme*n[0-9] | wc -w)
    if [ "$namespace_count" -eq "0" ]; then
        LogErr "No NVME namespaces detected inside the VM"
        SetTestStateFailed
        exit 0
    fi
    namespace_list=$(find /dev -name 'nvme*n[0-9]' | cut -d/ -f3)
    for namespace in ${namespace_list}; do
        # Remove previous partitions or RAID config
        umount "$namespace"
        (echo d; echo w) | fdisk "/dev/${namespace}"
        sync
        #Format and mount nvme to namespace
        Format_Mount_NVME "${namespace}" xfs
        #check how much is trimmed intially
        trim_init=$(fstrim  "$namespace" -v)
        if [ $? -ne 0 ]; then
            LogErr "Failed to check intial trim on ${namespace}"
            SetTestStateFailed
            exit 0
        else
            LogMsg "Initial Trim size :$trim_init"
        fi
        # Create files on the partition
        dd if=/dev/zero of="$namespace"/data bs=1G count=300
        if [ $? -ne 0 ]; then
            LogErr "Failed to create 300GB file on ${namespace}"
            SetTestStateFailed
            exit 0
        else
            LogMsg "Create 300GB file on ${namespace}"
        fi
        #check how much is trimmed after file is created
        trim_file=$(fstrim  "$namespace" -v)
        if [ $? -ne 0 ]; then
            LogErr "Failed to check trim size after file creation on ${namespace}"
            SetTestStateFailed
            exit 0
        else
            LogMsg "Trim size after file creation:$trim_file"
        fi
        # Delete file
        rm -rf "$namespace"/data
        if [ $? -ne 0 ]; then
            LogErr "Failed to ${namespace}/data"
            SetTestStateFailed
            exit 0
        fi
        #check how much is trimmed after file is created
        trim_final=$(fstrim  "$namespace" -v)
        if [ $? -ne 0 ]; then
            LogErr "Failed to check trim size after file creation on ${namespace}"
            SetTestStateFailed
            exit 0
        else
            LogMsg "Trim size after file creation:$trim_final"
        fi
        #check how much is trimmed after file is created
        if [ "$trim_final" -ne "$trim_init" ]; then
            LogErr "Final trim size does not match initial trim size"
            SetTestStateFailed
            exit 0
        else
            LogMsg "Final trim size matched with initial trim size"
        fi
        #unmont
        umount "$namespace"
        if [ $? -ne 0 ]; then
            LogErr "Failed to unmount ${namespace}"
            SetTestStateFailed
            exit 0
        else
            LogMsg "Unmounted ${namespace}"
        fi
        UpdateSummary "All the operations on ${namespace} worked as expected!"
    done
    # All the operations succeeded and the test is complete
    SetTestStateCompleted
    exit 0
}
#Run testcase
Run_Fstrim