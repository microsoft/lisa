#!/usr/bin/python
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
from azuremodules import *


import argparse
import sys
import time
        #for error checking
parser = argparse.ArgumentParser()

parser.add_argument('-e', '--expected', help='specify expected DiskSize in Byte', required=True)
args = parser.parse_args()
                #if no value specified then stop
expectedDiskSize = args.expected

def RunTest(expectedSize):
    UpdateState("TestRunning")
    RunLog.info("Checking DiskSize...")
    osDisk = GetOSDisk()
    output = Run("fdisk -l | awk '/" + osDisk + "/ {print $5;}' | awk 'NR==1'")
    ActualSize = float(output)

    if (ActualSize < expectedSize*1.1 and ActualSize > expectedSize*0.9) :
        RunLog.info('/dev/sda disk size is: %s', output)
        ResultLog.info('PASS')
        UpdateState("TestCompleted")
    else :
        RunLog.error('Getting the Disk SizeError over 10 percent different from Original OSImage: %s', output)
        ResultLog.error('FAIL')
        UpdateState("TestCompleted")

RunTest(float(expectedDiskSize))
