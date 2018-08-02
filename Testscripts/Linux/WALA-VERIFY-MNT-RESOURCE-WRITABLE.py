#!/usr/bin/python
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
from azuremodules import *

import sys

def RunTest():
    UpdateState("TestRunning")
    mntresource = GetResourceDiskMountPoint()
    RunLog.info('Mount point is %s' % mntresource)
    RunLog.info("creating a file in " + mntresource)
    temp = Run("echo DONE > " + mntresource + "/try.txt")
    temp = Run("cat " + mntresource + "/try.txt")
    output = temp
    if ("DONE" in output) :
        RunLog.info('file is successfully created in %s folder.' % mntresource)
        ResultLog.info('PASS')
    else :
        RunLog.error('failed to create file in %s folder.' % mntresource)
        ResultLog.error('FAIL')
    UpdateState("TestCompleted")

RunTest()
