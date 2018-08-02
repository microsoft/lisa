#!/usr/bin/python
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
from azuremodules import *

def RunTest(command):
    UpdateState("TestRunning")
    RunLog.info("Checking resource disc...")
    mountpoint = GetResourceDiskMountPoint()
    RunLog.info('Mount point is %s' % mountpoint)
    osdisk = GetOSDisk()
    if (osdisk == 'sdb') :
        mntresource = "/dev/sda1 on " + mountpoint
    else :
        mntresource = "/dev/sdb1 on " + mountpoint
    output = Run(command)
    if (mntresource in output) :
        RunLog.info('Resource disk is mounted successfully.')
        if ("ext4" in output) :
            RunLog.info('Resource disk is mounted as ext4')
        elif ("ext3" in output) :
            RunLog.info('Resource disk is mounted as ext3')
        else :
            RunLog.info('Unknown filesystem detected for resource disk')
            ResultLog.info("FAIL")
        ResultLog.info('PASS')
    else :
        RunLog.error('Resource Disk mount check failed. Mount out put is: %s', output)
        ResultLog.error('FAIL')
    UpdateState("TestCompleted")

RunTest("mount")
