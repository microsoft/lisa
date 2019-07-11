#!/usr/bin/python
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
from azuremodules import *
import os.path
import re

swap_check_result = False
root_device_timeout_check_result = False
mtab_entry_check_result = False
verify_UUID_result = False


def CheckSwap(command):
    global swap_check_result
    RunLog.info("Checking if swap disk is enable or not..")
    RunLog.info("Executing swapon -s..")
    temp = Run(command)
    lsblkOutput = Run("lsblk")
    output = temp
    if os.path.exists("/etc/lsb-release") and int(Run("cat /etc/lsb-release | grep -i coreos | wc -l")) > 0:
        waagent_conf_file = "/usr/share/oem/waagent.conf"
    elif (DetectDistro()[0] == 'clear-linux-os'):
        waagent_conf_file = "/usr/share/defaults/waagent/waagent.conf"
    else:
        waagent_conf_file = "/etc/waagent.conf"

    RunLog.info("Read ResourceDisk.EnableSwap from " + waagent_conf_file + "..")
    outputlist=open(waagent_conf_file)

    for line in outputlist:
        if(line.find("ResourceDisk.EnableSwap")!=-1):
                break
    RunLog.info("Value " + line.strip().split()[0] + " in " + waagent_conf_file)
    if ((("swap" in output) or ("SWAP" in lsblkOutput)) and (line.strip().split()[0] == "ResourceDisk.EnableSwap=n")):
        RunLog.error('Swap is enabled. Swap should not be enabled.')
        RunLog.error('%s', output)
    elif (((output.find("swap")==-1) or ("SWAP" in lsblkOutput)) and (line.strip().split()[0] == "ResourceDisk.EnableSwap=y")):
        RunLog.error('Swap is disabled. Swap should be enabled.')
        RunLog.error('%s', output)
        RunLog.info("Pleae check value of setting ResourceDisk.SwapSizeMB")
    elif((("swap" in output) or ("SWAP" in lsblkOutput)) and (line.strip().split()[0] == "ResourceDisk.EnableSwap=y")):
        RunLog.info('swap is enabled.')
        if(IsUbuntu()) :
            mntresource = "/mnt"
        else:
            mntresource = "/mnt/resource"
        swapfile = mntresource + "/swapfile"
        if(swapfile in output):
            RunLog.info("swap is enabled on resource disk")
            swap_check_result = True
        else:
            RunLog.info("swap is not enabled on resource disk")
    elif(((output.find("swap")==-1) or ("SWAP" in lsblkOutput)) and (line.strip().split()[0] == "ResourceDisk.EnableSwap=n")):
        RunLog.info('swap is disabled.')
        swap_check_result = True


def CheckMtabEntry(command):
    global mtab_entry_check_result
    RunLog.info("Checking for resource disk entry in /etc/mtab start...")
    mountpoint = GetResourceDiskMountPoint()
    RunLog.info('Mount point is %s' % mountpoint)
    osdisk = GetOSDisk()
    output = Run(command)
    if (osdisk == 'sdb') :
        mntresource = "/dev/sda1 " + mountpoint
    else :
        mntresource = "/dev/sdb1 " + mountpoint

    if mntresource in output:
        RunLog.info('Resource disk entry is present.')
        mtab_entry_check_result = True
        for each in output.splitlines():
            if mntresource in each:
                RunLog.info("%s", each)
    else:
        RunLog.error('Resource disk entry is not present.')


def VerifyUUID():
    global verify_UUID_result
    RunLog.info("Verify UUID start...")
    uuid_from_dmesg = 0
    uuid_from_blkid = 0
    dmesg_dev_count = 0
    uuid_from_dmesg_root = 0
    uuid_from_blkid_root = 0
    uuid_from_fstab_root = 0
    output = JustRun("dmesg")
    output = output.lower()
    filter_condition_dmesg = r'uuid(=|/|-)(.*?)([ \t]|[\.])'
    filter_condition_blkid = r'(label=\"(.*?)\"|)[ \t]uuid=\"(.*?)\"[ \t]'
    filter_condition_fstab = r'uuid(/|=)(\S+)[ \t]+\/(.*?)[ \t]+(.*?)[ \t]'
    filter_condition_dmesg_root = r'root=/(.*?)[ \t]'
    filter_condition_fstab_root = r'/(.*?)[ \t]/[ \t]'
    filter_condition_blkid_root = r'/(.*?)\:[ \t]label=\"(.*?)\"[ \t]uuid=\"(.*?)\"[ \t]'

    dmesg_dev_count = output.count('command line:.*root=/dev/sd')

    outputlist = re.split("\n", output)
    for line in outputlist:
        matchObj = re.search(filter_condition_dmesg, line, re.IGNORECASE)

        if matchObj:
           uuid_from_dmesg = matchObj.groups()[-2]
           uuid_from_dmesg = uuid_from_dmesg.replace("\\x2d", "-")

    for line in outputlist:
        matchObj = re.search(filter_condition_dmesg_root, line, re.IGNORECASE)

        if matchObj:
           uuid_from_dmesg_root = matchObj.groups()

    output = JustRun("blkid")
    output = output.lower()

    outputlist = re.split("\n", output)

    if uuid_from_dmesg_root:
        for line in outputlist:
            matchObj = re.search(filter_condition_blkid_root, line, re.IGNORECASE)

            if matchObj:
                uuid_from_blkid_root = matchObj.groups()[-3]
                if (uuid_from_blkid_root == uuid_from_dmesg_root[-1]):
                    uuid_from_blkid = matchObj.groups()[-1]

    for line in outputlist:
        matchObj = re.search(filter_condition_blkid, line, re.IGNORECASE)

        if (matchObj and uuid_from_dmesg == matchObj.groups()[-1]):
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

    for line in outputlist:
        matchObj = re.search(filter_condition_fstab_root, line, re.IGNORECASE)

        if matchObj:
                uuid_from_fstab_root = matchObj.groups()

    if((uuid_from_dmesg and uuid_from_fstab and (uuid_from_dmesg == uuid_from_fstab) and (dmesg_dev_count == 0) and (fstab_dev_count == 0)) or (uuid_from_dmesg_root == uuid_from_fstab_root) or (uuid_from_fstab == uuid_from_blkid)):
        verify_UUID_result = True
    elif (DetectDistro()[0] == 'coreos'):
        output = JustRun("dmesg | grep root")
        if ("root=LABEL" in output):
            RunLog.info('CoreOS uses disk labels to specify drives.')
            verify_UUID_result = True
        else:
            RunLog.info('root partition is not mounted using LABEL in dmesg.')
    elif (DetectDistro()[0] == 'clear-linux-os'):
        output_byuuid = Run('ls -l /dev/disk/by-partuuid | grep -i sda')
        output_byuuid = output_byuuid.split('\n')[0].split(' ')[-3]
        output = JustRun("dmesg | grep -e root=PARTUUID={0}" \
                 .format(output_byuuid))
        if (output):
            verify_UUID_result = True
        else:
            RunLog.info("Verify UUID failed.")
    elif(DetectDistro()[0] == 'ubuntu' and fstab_dev_count == 1):
        if (uuid_from_dmesg != 0 and uuid_from_fstab != 0 and uuid_from_dmesg == uuid_from_fstab and dmesg_dev_count == 0):
           verify_UUID_result = True
        else:
           RunLog.info("Verify UUID failed.")
    else:
        if (uuid_from_dmesg == 0):
            RunLog.info('/ partition is not mounted using UUID in dmesg.')
        if (uuid_from_fstab == 0):
            RunLog.info('/ partition is not mounted using UUID in /etc/fstab.')
        if (uuid_from_dmesg != uuid_from_fstab):
            RunLog.info(' UUID is not same in dmesg and /etc/fstab.')
        if (dmesg_dev_count != 0):
            RunLog.info('Found disks mounted without using UUID in dmesg.')
        if (fstab_dev_count != 0):
            RunLog.info('Found disks mounted without using UUID in /etc/fstab.')

        RunLog.info("Verify UUID failed.")


def CheckRootDeviceTimeout(command):
    global root_device_timeout_check_result
    RunLog.info("Checking root device timeout start...")
    temp = Run(command)
    rootDeviceTimeout = 300
    output = int(temp)
    if (output == rootDeviceTimeout) :
        RunLog.info('SDA timeout value is %s', output)
        root_device_timeout_check_result = True
    else:
        RunLog.error('SDA timeout value is %s', output)


def RunTest():
    UpdateState("TestRunning")
    CheckSwap("swapon -s")
    CheckMtabEntry("cat /etc/mtab")
    VerifyUUID()
    CheckRootDeviceTimeout("cat /sys/block/sda/device/timeout")

    if (swap_check_result and root_device_timeout_check_result and mtab_entry_check_result and verify_UUID_result):
        ResultLog.info('PASS')
    else:
        ResultLog.info('FAIL')

    UpdateState("TestCompleted")


RunTest()
