#!/usr/bin/python
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
from azuremodules import *
import random
import string
from random import randint
import re

file_path = os.path.dirname(os.path.realpath(__file__))
constants_path = os.path.join(file_path, "constants.sh")
params = GetParams(constants_path)
expectedHostname = params["ROLENAME"]
MONITOR_ENABLED = r'Provisioning.MonitorHostName\s*=\s*(\S+)'
AGENT_CONFIG_FILE = Run("find / -name waagent.conf")
AGENT_CONFIG_FILE = AGENT_CONFIG_FILE.rstrip()


def is_monitor_hostname_enabled():
    with open(AGENT_CONFIG_FILE, 'r') as config_fh:
        for line in config_fh.readlines():
            if not line.startswith('#'):
                update_match = re.match(MONITOR_ENABLED, line, re.IGNORECASE)
                if update_match:
                    return update_match.groups()[0].lower() == 'y'
    return True


def get_random_alphaNumeric_string(stringLength=8):
    lettersAndDigits = string.ascii_letters + string.digits
    return ''.join((random.choice(lettersAndDigits) for i in range(stringLength)))


def RunTest(expectedHost):
    UpdateState("TestRunning")
    if not is_monitor_hostname_enabled():
        RunLog.info("The MonitorHostName is not enabled")
        Run("sed -i s/Provisioning.MonitorHostName=n/Provisioning.MonitorHostName=y/g " + AGENT_CONFIG_FILE)
        Run("(service waagent restart || systemctl restart waagent || service walinuxagent restart || systemctl restart walinuxagent) > /dev/null 2>&1")

    if CheckHostName(expectedHost) and ChangeHostName(expectedHost):
        Run("hostname " + expectedHost)
        RunLog.info('Current hostname is set as expected')
        ResultLog.info('PASS')
        UpdateState("TestCompleted")
    else:
        Run("hostname " + expectedHost)
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


def ChangeHostName(expectedHost):
    changed_hostname = get_random_alphaNumeric_string(randint(1, 63))
    RunLog.info("Change hostname into " + changed_hostname)
    Run("hostname " + changed_hostname)
    fail_error_warn_count = Run("tail -f waagent.log | grep -E 'fail|error|warning' | wc -l")
    RunLog.info("Start to sleep for 120 seconds.")
    Run("sleep 120")
    expected_filter_string = "Detected hostname change: {0} -> {1}".format(expectedHost, changed_hostname)
    matchCount = Run("grep -i '"+expected_filter_string+"' /var/log/waagent.log | wc -l")
    RunLog.info('Get matchCount {0}'.format(matchCount))
    if int(matchCount.rstrip()) == 1 and CheckHostName(changed_hostname) and int(fail_error_warn_count.rstrip()) == 0:
        return True
    else:
        return False

RunTest(expectedHostname)
