#!/bin/bash

# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
# Description:
# Basic NVME test script:
# - It checks if NVME namespace is available in /dev (e.g. /dev/nvme0n1)
# - Compares the number of namespaces with the number of devices
# - Installs nvme-cli and checks the listing of the device
# - Azure only: It compares available namespaces with the number of vCPUs
#   The ratios should be 1 NVME device / 8 vCPUs
######################################################################

. utils.sh || {
    echo "ERROR: unable to source utils.sh!"
    echo "TestAborted" > state.txt
    exit 0
}
UtilsInit

# Count the NVME disks
disk_count=$(ls -l /dev | grep -w nvme[0-9]$ | awk '{print $10}' | wc -l)
if [ "$disk_count" -eq "0" ]; then
    LogErr "No NVME disks were detected inside the VM"
    SetTestStateFailed
    exit 0
fi

if [ "$rescind_pci" = "yes" ]; then
    # call rescind function with param NVMe
    if ! RescindPCI "NVME"; then
        LogErr "Could not rescind pci device."
        SetTestStateFailed
        exit 0
    fi
fi

# Count NVME namespaces
namespace_count=$(ls -l /dev | grep -w nvme[0-9]n[0-9]$ | awk '{print $10}' | wc -l)
if [ "$namespace_count" -eq "0" ]; then
    LogErr "No NVME namespaces detected inside the VM"
    SetTestStateFailed
    exit 0
fi

# NVME namespaces should match the disks
if [ "$namespace_count" -ne "$disk_count" ]; then
    LogErr "NVME disks and namespaces mismatch"
    LogErr "Disk count ${disk_count}, Namespace Count ${namespace_count}"
    SetTestStateFailed
    exit 0
fi

# Install nvme-cli tool
update_repos
install_package "nvme-cli"

# Check namespaces in nvme cli
namespace_list=$(ls -l /dev | grep -w nvme[0-9]n[0-9]$ | awk '{print $10}')
for namespace in ${namespace_list}; do
    nvme list | grep -w "$namespace"
    if [ $? -ne 0 ]; then
        LogErr "NVME namespace ${namespace} was not detected by nvme-cli"
        SetTestStateFailed
        exit 0
    else
        echo "NVME namespace ${namespace} was detected by nvme-cli"
        UpdateSummary "${namespace} detected!"
    fi
done

# Only for Azure. Check if namespace count is in line with expected number of vCPUs.
# The expected ratio is 1 NVME disk to 8 vCPU
if [ ! -e platform.txt ]; then
    expected_namespace_count=$(($(nproc) / 8))
    if [ "$namespace_count" -ne "$expected_namespace_count" ]; then
        LogErr "CPU to NVME devices ratio is not 8/1!"
        LogErr "Expected NVME count: ${expected_namespace_count}. Actual count: ${namespace_count}"
        SetTestStateFailed
        exit 0
    else
        LogMsg "CPU to NVME devices ratio is 8/1!"
    fi
fi
SetTestStateCompleted
exit 0