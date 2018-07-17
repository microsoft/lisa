#!/usr/bin/python
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
from azuremodules import *
import sys
import time
import re
import linecache

def RunTest():
    UpdateState("TestRunning")
    uuid_from_demesg = 0
    dmsg_dev_count = 0
    output = JustRun("dmesg")
    output = output.lower()
    filter_condition_dmesg = r'.*root=UUID=(.*?) .*'
    filter_condition_fstab = r'.*UUID=(.*?)[ \t]+\/[ \t]+'
    if (DetectDistro()[0] == 'opensuse' or DetectDistro()[0] == 'SUSE'or DetectDistro()[0] == 'sles'):
        filter_condition_dmesg = r'.*root=/dev/disk/by-uuid/(.*?) .*'
        filter_condition_fstab = r'.*/dev/disk/by-uuid/(.*?)[ \t]+\/[ \t]+'

    dmsg_dev_count = output.count('command line:.*root=/dev/sd')

    outputlist = re.split("\n", output)
    for line in outputlist:
        matchObj = re.match(filter_condition_dmesg, line, re.M|re.I)

        if matchObj:
           uuid_from_demesg = matchObj.group(1)
           
    uuid_from_fstab = 0
    fstab_dev_count = 0
    fstab_dev_count = output = JustRun("cat /etc/fstab")
    fstab_dev_count = output.count('/dev/sd')

    outputlist = re.split("\n", output)
    for line in outputlist:
        matchObj = re.match(filter_condition_fstab, line, re.M|re.I)
        #matchObj = re.match( r'.*UUID=(.*?)[ \t]*/ .*', line, re.M|re.I)

        if matchObj:
           uuid_from_fstab = matchObj.group(1)

    if(uuid_from_demesg and uuid_from_fstab and (uuid_from_demesg == uuid_from_fstab) and (dmsg_dev_count == 0) and (fstab_dev_count == 0)):
        ResultLog.info('PASS')
        #print "UUID are valid and matched"
    elif (DetectDistro()[0] == 'coreos'):
        output = JustRun("dmesg | grep root")
        if ("root=LABEL" in output):
            RunLog.info('CoreOS uses disk labels to specify drives.')
            ResultLog.info('PASS')
        else:
            RunLog.info('root partition is not mounted using LABEL in dmesg.')
            ResultLog.info('FAIL')
    elif(DetectDistro()[0] == 'ubuntu' and fstab_dev_count == 1):
        if (uuid_from_demesg != 0 and uuid_from_fstab != 0 and uuid_from_demesg == uuid_from_fstab and dmsg_dev_count == 0): 
           ResultLog.info('PASS')  
        else:
           ResultLog.info('FAIL')  
    else:
        
        if (uuid_from_demesg == 0): 
            RunLog.info('/ partition is not mounted using UUID in dmesg.')
        if (uuid_from_fstab == 0): 
            RunLog.info('/ partition is not mounted using UUID in /etc/fstab.')
        if (uuid_from_demesg != uuid_from_fstab):
            RunLog.info(' UUID is not same in dmesg and /etc/fstab.')
        if (dmsg_dev_count != 0):
            RunLog.info('Found disks mounted without using UUID in dmesg.')
        if (fstab_dev_count != 0):
            RunLog.info('Found disks mounted without using UUID in /etc/fstab.')

        ResultLog.info('FAIL')        
    UpdateState("TestCompleted")

RunTest()
