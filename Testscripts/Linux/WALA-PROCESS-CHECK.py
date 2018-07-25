#!/usr/bin/python
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
from azuremodules import *

def RunTest(command):
    UpdateState("TestRunning")
    RunLog.info("Checking WALinuxAgent in running processes")
    temp = Run(command)
    timeout = 0
    output = temp
    if ("waagent" in output) :
                    RunLog.info('waagent service present in running processes')
                    ResultLog.info('PASS')
                    UpdateState("TestCompleted")
    else:
                    RunLog.error('waagent service absent in running processes')
                    ResultLog.Error('FAIL')
                    UpdateState("TestCompleted")
        

RunTest("ps -ef | grep waagent | grep -v grep")

