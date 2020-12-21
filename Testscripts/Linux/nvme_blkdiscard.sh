#!/bin/bash

# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
# Description:
# Functional NVME test script. For each NVME device it does the following:
# - Partition nvme0n1 (a single partition). Create xfs filesystem and mount the partition.
# - Unmount the partition
# - Run "blkdiscard /dev/nvme0n1p1"
# - Try to mount the partition again “mount /dev/nvme0n1p1 mountPoint” – it should fail
##########################################################################################

. utils.sh || {
    echo "ERROR: unable to source utils.sh!"
    echo "TestAborted" > state.txt
    exit 0
}
UtilsInit

if [ "$DISTRO" == "ubuntu_14.04" ]; then
    LogMsg "${DISTRO} is not supported as it does not include blkdiscard."
    SetTestStateSkipped
    exit 0
fi

Run_Blkdiscard() {
    # Install nvme-cli tool
    update_repos
    install_nvme_cli
    # Count NVME namespaces
    namespace_count=$(ls /dev/ | grep -wc nvme[0-9]n[0-9]$)
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
        # Format and mount nvme to namespace
        Format_Mount_NVME ${namespace} xfs
        # unmont
        umount "$namespace"
        if [ $? -ne 0 ]; then
            LogErr "Failed to unmount ${namespace}"
            SetTestStateFailed
            exit 0
        else
            LogMsg "Unmounted ${namespace}"
        fi
        # Run blkdiscard on partition
        if [ "${DISTRO_NAME}" = "ubuntu" ] && [ ${DISTRO_VERSION} = "20.10" ]; then
            blkdiscard -f -v "/dev/${namespace}p1"
        else
            blkdiscard -v "/dev/${namespace}p1"
        fi
        if [ $? -ne 0 ]; then
            LogErr "Failed to run blkdiscard on ${namespace}"
            SetTestStateFailed
            exit 0
        else
            LogMsg "blkdiscard ran successfully"
        fi
        # Check mount after discard
        mount "/dev/${namespace}p1" "$namespace"
        if [ $? -eq 0 ]; then
            LogErr "Mounted ${namespace}p1 Test failed"
            SetTestStateFailed
            exit 0
        else
            LogMsg "Failed to mount ${namespace}p1 blkdiscard successful"
        fi
        UpdateSummary "All the operations on ${namespace} worked as expected!"
    done
    # All the operations succeeded and the test is complete
    SetTestStateCompleted
    exit 0
}

# Run testcase
Run_Blkdiscard
