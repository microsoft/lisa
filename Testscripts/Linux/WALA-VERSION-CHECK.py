#!/usr/bin/python
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
import argparse
import sys
import re
from azuremodules import *

file_path = os.path.dirname(os.path.realpath(__file__))
constants_path = os.path.join(file_path, "constants.sh")
params = GetParams(constants_path)
distro = params["DETECTED_DISTRO"]

def RunTest(command):
    UpdateState("TestRunning")
    RunLog.info("Checking WALinuxAgent Version")
    output = Run(command)
    ExpectedVersionPattern = "WALinuxAgent\-\d[\.\d]+.*\ running\ on.*"
    RegExp = re.compile(ExpectedVersionPattern)

    if (RegExp.match(output)) :
        RunLog.info('Waagent is in Latest Version .. - %s', output)
        ResultLog.info('PASS')
        UpdateState("TestCompleted")
    else :
        RunLog.error('Waagent version is differnt than required.')
        RunLog.error('Current version - %s', output)
        RunLog.error('Expected version pattern - %s', ExpectedVersionPattern)
        ResultLog.error('FAIL')
        UpdateState("TestCompleted")

if(distro == "COREOS"):
    RunTest("waagent --version")
else:
    output = Run("ps aux | grep waagent | grep python | grep -v 'ps aux | grep waagent | grep python'")
    if ("python3" in output) :
        RunTest("/usr/bin/python3 /usr/sbin/waagent --version")
    else :
        RunTest("/usr/sbin/waagent --version")