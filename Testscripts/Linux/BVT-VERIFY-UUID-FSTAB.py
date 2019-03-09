#!/usr/bin/python
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
from azuremodules import *
import re


def RunTest():
    UpdateState("TestRunning")
    uuid_from_demesg = 0
    uuid_from_blkid = 0
    dmsg_dev_count = 0
    output = JustRun("dmesg")
    output = output.lower()
    filter_condition_dmesg = r'uuid(=|/|-)(.*?)([ \t]|[\.])'
    filter_condition_blkid = r'(LABEL=\"(.*?)\"|)[ \t]uuid=\"(.*?)\"[ \t]'
    filter_condition_fstab = r'uuid(/|=)(\S+)[ \t]+\/(.*?)[ \t]+(.*?)[ \t]'

    dmsg_dev_count = output.count('command line:.*root=/dev/sd')

    outputlist = re.split("\n", output)
    for line in outputlist:
        matchObj = re.search(filter_condition_dmesg, line, re.IGNORECASE)

        if matchObj:
           uuid_from_demesg = matchObj.groups()[-2]

    uuid_from_demesg = uuid_from_demesg.replace("\\x2d", "-")

    output = JustRun("blkid")
    output = output.lower()

    outputlist = re.split("\n", output)
    for line in outputlist:
        matchObj = re.search(filter_condition_blkid, line, re.IGNORECASE)

        if (matchObj and uuid_from_demesg == matchObj.groups()[-1]):
            uuid_from_blkid = matchObj.groups()[-1]

    uuid_from_fstab = 0
    fstab_dev_count = 0
    fstab_dev_count = output = JustRun("cat /etc/fstab")
    fstab_dev_count = output.count('/dev/sd')

    outputlist = re.split("\n", output)
    for line in outputlist:
        matchObj = re.search(filter_condition_fstab, line, re.IGNORECASE)

        if matchObj:
            if (uuid_from_blkid == matchObj.groups()[-3]):
                uuid_from_fstab = matchObj.groups()[-3]

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
    elif (DetectDistro()[0] == 'clear-linux-os'):
        output_byuuid = Run('ls -l /dev/disk/by-partuuid | grep -i sda')
        output_byuuid = output_byuuid.split('\n')[0].split(' ')[-3]
        output = JustRun("dmesg | grep -e root=PARTUUID={0}" \
                 .format(output_byuuid))
        if (output):
            ResultLog.info('PASS')
        else:
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
