#!/usr/bin/python
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
from azuremodules import *

def RunTest(command):
    UpdateState("TestRunning")
    mountpoint = GetResourceDiskMountPoint()
    RunLog.info('Mount point is %s' % mountpoint)
    osdisk = GetOSDisk()
    RunLog.info("Checking for resource disk entry in /etc/mtab.")
    output = Run(command)
    if (osdisk == 'sdb') :
        mntresource = "/dev/sda1 " + mountpoint
    else :
        mntresource = "/dev/sdb1 " + mountpoint

    if mntresource in output:
        RunLog.info('Resource disk entry is present.')
        ResultLog.info('PASS')
        for each in output.splitlines():
            if mntresource in each:
                RunLog.info("%s", each)
    else:
        RunLog.error('Resource disk entry is not present.')
        ResultLog.error('FAIL')
    UpdateState("TestCompleted")

RunTest("cat /etc/mtab")
