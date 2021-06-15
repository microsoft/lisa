#!/bin/bash

# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
# Source utils.sh
. utils.sh || {
    echo "Error: unable to source utils.sh!"
    echo "TestAborted" > state.txt
    exit 2
}
# Source constants file and initialize most common variables
UtilsInit
# Check if Variable in Const file is present or not
if [ ! ${iozoneVers} ]; then
    LogErr "No IOZONE variable in constants.sh"
    SetTestStateAborted
    exit 1
fi
# Download iozone
curl $iozonesrclink/iozone$iozoneVers.tar > iozone$iozoneVers.tar
sts=$?
if [ 0 -ne ${sts} ]; then
    msg="iozone download failed ${sts}"
    LogErr "$msg"
    UpdateSummary "$msg"
    SetTestStateAborted
    exit 2
else
    LogMsg "iozone v$iozoneVers download: Success"
fi
# Make sure the iozone exists
IOZONE=iozone$iozoneVers.tar
if [ ! -e ${IOZONE} ];
then
    LogErr "Cannot find iozone file."
    SetTestStateAborted
    exit 1
fi
# Get Root Directory of tarball
ROOTDIR=$(tar -tvf ${IOZONE} | head -n 1 | awk -F " " '{print $6}' | awk -F "/" '{print $1}')
# Now Extract the Tar Ball.
tar -xvf ${IOZONE}
sts=$?
if [ 0 -ne ${sts} ]; then
    LogErr "Failed to extract Iozone tarball"
    SetTestStateAborted
    exit 1
fi
# cd in to directory
if [ !  ${ROOTDIR} ];
then
    LogErr "Cannot find ROOTDIR."
    SetTestStateAborted
    exit 1
fi
if [[ $(detect_linux_distribution) == 'mariner' ]]; then
    install_package "make gcc kernel-headers binutils glibc-devel"
fi
cd ${ROOTDIR}/src/current
# Compile iozone
make linux
sts=$?
if [ 0 -ne ${sts} ]; then
    msg="make linux : Failed ${sts}"
    LogErr "$msg"
    UpdateSummary "$msg"
    SetTestStateAborted
    exit 2
else
    LogMsg "make linux : Success"
fi
# Run Iozone
while true ; do ./iozone -ag 10G   ; done > /dev/null 2>&1 &
sts=$?
if [ 0 -ne ${sts} ]; then
    msg="running IOzone  Failed ${sts}"
    LogErr "$msg"
    UpdateSummary "$msg"
    SetTestStateAborted
    exit 2
else
    LogMsg "Running IoZone : Success"
fi
SetTestStateCompleted
exit 0
