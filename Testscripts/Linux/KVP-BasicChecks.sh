#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

# Description:
# 1. verify that the KVP Daemon is running
# 2. run the KVP client tool and verify that the data pools are created and accessible
# 3. check kvp_pool file permission is 644
# 4. check kernel version supports hv_kvp
# 5. Use lsof to check the opened file number belonging to hypervkvp process does not increase
#    continually. If this number increases, maybe file descriptors are not closed properly.
#    Here check duration is after 2 minutes.
# 6. Check if KVP pool 3 file has a size greater than zero.
# 7. At least 11 (default value, can be changed in xml) items are present in pool 3.

. utils.sh || {
    echo "Error: unable to source utils.sh!"
    exit 0
}
# Source constants file and initialize most common variables
UtilsInit
homeDir=$(dirname "$0")
#
# Make sure constants.sh contains the variables we expect
#
if [ "${kvp_pool:-UNDEFINED}" = "UNDEFINED" ]; then
    LogErr "The test parameter kvp_pool number is not defined in constants.sh"
    SetTestStateAborted
    exit 0
fi

if [ "${kvp_items:-UNDEFINED}" = "UNDEFINED" ]; then
    LogErr "The test parameter kvp_items is not defined in constants.sh"
    SetTestStateAborted
    exit 0
fi

#
# 1. verify that the KVP Daemon is running
#
pid=$(pgrep "hypervkvpd|hv_kvp_daemon")
if [ $? -ne 0 ]; then
    LogMsg "KVP Daemon is not running by default"
    UpdateSummary "KVP Daemon is not running by default"
    SetTestStateSkipped
    exit 0
fi
LogMsg "KVP Daemon is running"
UpdateSummary "KVP Daemon is running"

#
# 2. check kernel version supports hv_kvp
#
CheckVMFeatureSupportStatus "3.10.0-514"
if [ $? -eq 0 ]; then
    ls -la /proc/"$pid"/fd | grep /dev/vmbus/hv_kvp
    if [ $? -ne 0 ]; then
        LogErr "There is no hv_kvp in the /proc/$pid/fd"
        SetTestStateFailed
        exit 0
    fi
else
    LogMsg "This kernel version does not support /dev/vmbus/hv_kvp, skip this step"
fi

#
# 3. run the KVP client tool and verify that the data pools are created and accessible
#
uname -a | grep x86_64
if [ $? -eq 0 ]; then
    LogMsg "64 bit architecture was detected"
    kvp_client="kvp_client64"
else
    uname -a | grep i686
    if [ $? -eq 0 ]; then
        LogMsg "32 bit architecture was detected"
        kvp_client="kvp_client32"
    else
        LogErr "Unable to detect OS architecture"
        SetTestStateAborted
        exit 0
    fi
fi

#
# Make sure we have the kvp_client tool
#
if [ ! -e ${homeDir}/${kvp_client} ]; then
    LogErr "${kvp_client} tool is not on the system"
    SetTestStateAborted
    exit 0
fi

#
# 4. check kvp_pool count
#
chmod +x ${homeDir}/${kvp_client}
LogMsg "Output of ${kvp_client}: ${homeDir}/${kvp_client}"
poolCount=$(${homeDir}/$kvp_client | grep -i pool | wc -l)
LogMsg "KVP pool count: $poolCount}"
if [ "$poolCount" -ne 5 ]; then
    LogErr "Could not find a total of 5 KVP data pools"
    SetTestStateFailed
    exit 0
fi
LogMsg "Verified that all 5 KVP data pools are listed properly"
UpdateSummary "Verified that all 5 KVP data pools are listed properly"

#
# 5. check kvp_pool file permission is 644
#
permCount=$(stat -c %a /var/lib/hyperv/.kvp_pool* | grep 644 | wc -l)
LogMsg "KVP pool file with 644 permission count: $permCount}"
if [ "$permCount" -ne 5 ]; then
    LogErr ".kvp_pool file permission is incorrect "
    SetTestStateFailed
    exit 0
fi
LogMsg "Verified that .kvp_pool files permission is 644"
UpdateSummary "Verified that .kvp_pool files permission is 644"

#
# 6. check lsof number for kvp whether increase or not after sleep 2 minutes
#
GetDistro
command -v lsof > /dev/null
if [ $? -ne 0 ]; then
    install_package lsof
fi

lsofCountBegin=$(lsof | grep -c kvp)
sleep 120
lsofCountEnd=$(lsof | grep -c kvp)
LogMsg "lsof for kvp is $lsofCountBegin, after 2 minutes is $lsofCountEnd"
if [ "$lsofCountBegin" -ne "$lsofCountEnd" ]; then
    LogErr "hypervkvp opened file number has changed from $lsofCountBegin to $lsofCountEnd"
    SetTestStateFailed
    exit 0
fi
UpdateSummary "Verified that lsof for kvp is $lsofCountBegin, after 2 minutes is $lsofCountEnd"

#
# 6. Check if KVP pool 3 file has a size greater than zero
#
poolFileSize=$(ls -l /var/lib/hyperv/.kvp_pool_"${kvp_pool}" | awk '{print $5}')
LogMsg "Count of kvp pool file >0 : $poolFileSize"
if [ "$poolFileSize" -eq 0 ]; then
    LogErr "The kvp_pool_${kvp_pool} file size is zero"
    SetTestStateFailed
    exit 0
fi

#
# 7. Check the number of records in Pool 3.
# Below 11 entries (default value) the test will fail
#
pool_records=$(${homeDir}/${kvp_client} "$kvp_pool" | wc -l)
LogMsg "KVP items in pool ${kvp_pool}: ${pool_records}"
if [ "$pool_records" -eq 0 ]; then
    LogErr "Could not list the KVP Items in pool ${kvp_pool}"
    SetTestStateFailed
    exit 0
fi
UpdateSummary "KVP items in pool ${kvp_pool}: ${pool_records}"

poolItemNumber=$(${homeDir}/${kvp_client} "$kvp_pool" | awk 'FNR==2 {print $4}')
if [ "$poolItemNumber" -lt "$kvp_items" ]; then
    LogErr "Pool $kvp_pool has only $poolItemNumber items. We need $kvp_items items or more"
    SetTestStateFailed
    exit 0
fi

actualPoolItemNumber=$(${homeDir}/${kvp_client} "$kvp_pool" | grep Key | wc -l)
if [ "$poolItemNumber" -ne "$actualPoolItemNumber" ]; then
    LogErr "Pool $kvp_pool reported $poolItemNumber items but actually has $actualPoolItemNumber items"
    SetTestStateFailed
    exit 0
fi

SetTestStateCompleted
exit 0
