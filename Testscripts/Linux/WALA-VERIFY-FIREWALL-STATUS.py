#!/usr/bin/python
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
from azuremodules import *

import sys
import time

def RunTest():
    UpdateState("TestRunning")
    RunLog.info("Checking firewall status using iptables...")
    output = Run("iptables -L > iptables.txt")
    output = Run("cat iptables.txt")
    dropRulesCount = GetStringMatchCount("iptables.txt", "policy DROP")
    dropItemsCount = GetStringMatchCount("iptables.txt", "DROP")

    if (dropRulesCount <= 0 and dropItemsCount <= 0) :
        RunLog.info('No iptables DROP rules found, and Firewall is disabled. iptables output is: %s', output)
        ResultLog.info('PASS')
        UpdateState("TestCompleted")
    else :
        RunLog.info('A few iptables DROP rules found, looks like firewall is enabled. iptables output is: %s', output)
        ResultLog.error('FAIL')
        UpdateState("TestCompleted")

RunTest()
