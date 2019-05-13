#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.


# Source utils.sh
. utils.sh || {
    echo "ERROR: unable to source utils.sh!"
    echo "TestAborted" > state.txt
    exit 2
}
UtilsInit

install_package "pciutils lshw"

if [ ! -z "$expectedNvme" ] && [ "$expectedNvme" -gt 0 ]; then
    # Count the NVME disks
    disk_count=$(ls -l /dev | grep -w nvme[0-9]$ | awk '{print $10}' | wc -l)
    if [ "$disk_count" -ne "$expectedNvme" ]; then
        LogErr "NVME disks count does not match expected inside the VM, expected $expectedNvme found $disk_count"
        LogErr "lspci output: $(lspci)"
        LogErr "lshw output: $(lshw -c storage -businfo)"
        SetTestStateFailed
        exit 0
    fi
fi

if [ ! -z "$expectedSriov" ] && [ "$expectedSriov" -gt 0 ]; then
    #count SR-IOV NICs
    nics_count=$(find /sys/devices -name net -a -ipath '*vmbus*' | grep -c pci)
    if [ "$nics_count" -ne "$expectedSriov" ]; then
        LogErr "SR-IOV NICs count does not match expected inside the VM, expected $expectedSriov found $nics_count"
        LogErr "lspci output: $(lspci)"
        LogErr "lshw output: $(lshw -c network -businfo)"
        SetTestStateFailed
        exit 0
    fi
fi

if [ ! -z "$expectedGpu" ] && [ "$expectedGpu" -gt 0 ]; then
    #count GPUs
    gpu_count=$(lspci | grep -ic nvidia)
    if [ "$gpu_count" -ne "$expectedGpu" ]; then
        LogErr "GPU count does not match expected inside the VM, expected $expectedGpu found $gpu_count"
        LogErr "lspci output: $(lspci)"
        LogErr "lshw output: $(lshw -c display -businfo)"
        SetTestStateFailed
        exit 0
    fi
fi

if ! DisableEnablePCI "ALL"; then
    LogErr "Could not disable and reenable the pci devices."
    SetTestStateFailed
    exit 0
fi

SetTestStateCompleted
exit 0