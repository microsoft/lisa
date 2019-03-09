#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

. utils.sh || {
    echo "Error: unable to source utils.sh!"
    exit 0
}

UtilsInit

./check_traces.sh &

# Count the number of SCSI= and IDE= entries in constants
if [ -z "$diskCount" ]; then
    diskCount=0
    for entry in $(cat ./constants.sh)
    do
    # Convert to lower case
        lowStr="$(tr '[A-Z]' '[a-z' <<<"$entry")"

    # does it start wtih ide or scsi
        if [[ $lowStr == ide* ]];
        then
            diskCount=$((diskCount+1))
        fi

        if [[ $lowStr == scsi* ]];
        then
            diskCount=$((diskCount+1))
        fi
      done
fi

LogMsg "constants disk count = $diskCount"

### do fdisk to rescan the scsi bus
for i in {1..4}; do
    echo $i
    fdisk -l > /dev/null
done

# Compute the number of sd* drives on the system.
sdCount=0
sdCount=$(fdisk -l | grep -c "Disk /dev/sd*")

# Subtract the boot disk from the sdCount, then make
# sure the two disk counts match
sdCount=$((sdCount-2))
LogMsg "fdisk -l disk count = $sdCount"

if [ $sdCount == $diskCount ]; then
    LogErr "constants.sh disk count ($diskCount) does match disk count from /dev/sd* ($sdCount)"
    SetTestStateFailed
    exit 0
else
    if [ "$sdCount" == "0" ]; then
	    LogMsg "Hot remove of Disk was successful"
	else
	    LogErr "Disk count mismatch, count is $sdCount, expected $diskCount"
	    SetTestStateFailed
        exit 0
    fi
fi

LogMsg "Exiting with state: TestCompleted."
SetTestStateCompleted
exit 0
