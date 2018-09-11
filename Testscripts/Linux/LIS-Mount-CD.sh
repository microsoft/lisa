#!/bin/bash

# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
########################################################################

###############################################################
#
# Description:
#     This script was created to automate the testing of a Linux
#     Integration services. This script detects the CDROM
#     and performs read operations .
#
################################################################

dos2unix utils.sh
. utils.sh || {
    echo "Error: unable to source utils.sh!"
    exit 0
}

#
# Source constants file and initialize most common variables
#
UtilsInit

GetGuestGeneration
if [ $os_GENERATION -eq 1 ] && [ $HotAdd = "True" ]; then
    SetTestStateSkipped
    exit 0
fi

#
# Check if the CDROM module is loaded
#
if [[ -x $(which lsb_release 2>/dev/null) ]]; then
    os_VENDOR=$(lsb_release -i -s)
fi
if [ $os_VENDOR != "Ubuntu" ] && [ $os_VENDOR != "Debian" ]; then
    CD=`lsmod | grep 'ata_piix\|isofs'`
    if [[ $CD != "" ]] ; then
        module=`echo $CD | cut -d ' ' -f1`
        LogMsg "${module} module is present."
    else
        LogMsg "ata_piix module is not present in VM"
        LogMsg "Loading ata_piix module "
        insmod /lib/modules/`uname -r`/kernel/drivers/ata/ata_piix.ko
        sts=$?
        if [ 0 -ne ${sts} ]; then
            LogMsg "Unable to load ata_piix module"
            LogMsg "Aborting test."
            SetTestStateFailed
            exit 0
        else
            LogMsg "ata_piix module loaded inside the VM"
        fi
    fi
fi
sleep 1
LogMsg "Mount the CDROM"
for drive in $(ls /dev/sr*)
do
    blkid $drive
    if [ $? -eq 0 ]; then
        mount -o loop $drive /mnt/
        LogMsg "Mount the CDROM ${drive}"
        break
    fi
done
sts=$?
if [ 0 -ne ${sts} ]; then
    LogMsg "Unable to mount the CDROM"
    LogMsg "Mount CDROM failed: ${sts}"
    LogMsg "Aborting test."
    SetTestStateFailed
    exit 0
else
    LogMsg  "CDROM is mounted successfully inside the VM"
    LogMsg  "CDROM is detected inside the VM"
fi

LogMsg "Perform read operations on the CDROM"
cd /mnt/

ls /mnt
sts=$?
if [ 0 -ne ${sts} ]; then
    LogMsg "Unable to read data from the CDROM"
    LogMsg "Read data from CDROM failed: ${sts}"
    SetTestStateFailed
    exit 0
else
    LogMsg "Data read successfully from the CDROM"
fi

cd ~
umount /mnt/
sts=$?
if [ 0 -ne ${sts} ]; then
    LogMsg "Unable to unmount the CDROM"
    LogMsg "umount failed: ${sts}"
    LogMsg "Aborting test."
    SetTestStateFailed
    exit 0
else
    LogMsg  "CDROM unmounted successfully"
fi


#
# Check without multiple "medium not present" in dmesg log
# Refer to https://lkml.org/lkml/2016/5/23/332
#
logNum=`dmesg | grep -i "Medium not present" | wc -l`
if [ $logNum -gt 1 ];then
    LogMsg  "Error: Multiple 'medium not present' messages found in dmesg"
    SetTestStateFailed
    exit 0
fi

# Check for Call traces
CheckCallTracesWithDelay 20

LogMsg "Result: Test Completed Successfully"
SetTestStateCompleted
