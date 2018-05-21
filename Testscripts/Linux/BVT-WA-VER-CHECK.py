#!/usr/bin/python

import argparse
import sys
import re
from azuremodules import *

parser = argparse.ArgumentParser()

parser.add_argument('-d', '--distro', help='Please mention which distro you are testing', required=True, type = str)

args = parser.parse_args()
distro = args.distro

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