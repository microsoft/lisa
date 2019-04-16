#!/usr/bin/python
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

from azuremodules import *


def RunTest(command):
    UpdateState("TestStarted")
    hvModules=["hv_storvsc", "hv_netvsc", "hv_vmbus", "hv_utils", "hid_hyperv", ]
    configPath="/boot/config-$(uname -r)"
    if (DetectDistro()[0] == 'clear-linux-os'):
        configPath="/usr/lib/kernel/config-$(uname -r)"

    output = Run('grep CONFIG_HYPERV_STORAGE=y ' + configPath)
    if output:
        hvModules.remove("hv_storvsc")

    output = Run('grep CONFIG_HYPERV_NET=y ' + configPath)
    if output:
        hvModules.remove("hv_netvsc")

    output = Run('grep CONFIG_HYPERV=y ' + configPath)
    if output:
        hvModules.remove("hv_vmbus")

    output = Run('grep CONFIG_HYPERV_UTILS=y ' + configPath)
    if output:
        hvModules.remove("hv_utils")

    output = Run('grep CONFIG_HID_HYPERV_MOUSE=y ' + configPath)
    if output:
        hvModules.remove("hid_hyperv")

    totalModules = len(hvModules)
    presentModules = 0
    UpdateState("TestRunning")
    RunLog.info("Checking for hyperV modules.")
    temp = Run(command)
    output = temp
    for module in hvModules :
        if (module in output) :
            RunLog.info('Module %s : Present.', module)
            presentModules = presentModules + 1
        else :
            RunLog.error('Module %s : Absent.', module)
            
    if (totalModules == presentModules) :
        RunLog.info("All modules are present.")
        ResultLog.info('PASS')
        UpdateState("TestCompleted")
    else :
        RunLog.error('one or more module(s) are absent.')
        ResultLog.error('FAIL')
        UpdateState("TestCompleted")

RunTest("lsmod")