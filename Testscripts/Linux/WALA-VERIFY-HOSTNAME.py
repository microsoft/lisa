#!/usr/bin/python
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
from azuremodules import *

import argparse
import sys
import time
import re

file_path = os.path.dirname(os.path.realpath(__file__))
constants_path = os.path.join(file_path, "constants.sh")
params = GetParams(constants_path)
expectedHostname = params["ROLENAME"]

def RunTest(expectedHost):
    UpdateState("TestRunning")
    if CheckHostName(expectedHost) and CheckFQDN(expectedHost):
        ResultLog.info('PASS')
        UpdateState("TestCompleted")
    else:
        ResultLog.error('FAIL')
        UpdateState("TestCompleted")

def CheckHostName(expectedHost):
    RunLog.info("Checking hostname...")
    output = Run("hostname")
    if expectedHost.upper() in output.upper():
        RunLog.info('Hostname is set successfully to {0}'.format(expectedHost))
        return True
    else:
        RunLog.error('Hostname change failed. Current hostname : {0} Expected hostname : {1}'.format(output, expectedHost))
        return False

def CheckFQDN(expectedHost):
    RunLog.info("Checking fqdn...")
    [current_distro, distro_version] = DetectDistro()
    nslookupCmd = "nslookup {0}".format(expectedHost)
    if current_distro == 'coreos':
        nslookupCmd = "python nslookup.py -n {0}".format(expectedHost)
    output = Run(nslookupCmd)
    if re.search("server can't find", output) is None:
        RunLog.info('nslookup successfully for: {0}'.format(expectedHost))
        return True
    else:
        RunLog.error("nslookup failed for: {0}, {1}".format(expectedHost, output))
        return False

RunTest(expectedHostname)
