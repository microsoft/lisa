#!/usr/bin/python
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
from azuremodules import *
import os
import pwd
import re
import subprocess
import sys

if sys.version_info[0]== 3:
    import http.client as httpclient
elif sys.version_info[0] == 2:
    import httplib as httpclient

FIREWALL_USER = os.environ["SUDO_USER"]
EXECUTION_USER = "root"
WIRESERVER_ENDPOINT_FILE = '/var/lib/waagent/WireServerEndpoint'
VERSIONS_PATH = '/?comp=versions'
OS_ENABLE_FIREWALL_RX = r'OS.EnableFirewall\s*=\s*(\S+)'
AGENT_CONFIG_FILE = Run("find / -name waagent.conf")
AGENT_CONFIG_FILE = AGENT_CONFIG_FILE.rstrip()


def is_firewall_enabled():
    with open(AGENT_CONFIG_FILE, 'r') as config_fh:
        for line in config_fh.readlines():
            if not line.startswith('#'):
                update_match = re.match(OS_ENABLE_FIREWALL_RX, line, re.IGNORECASE)
                if update_match:
                    return update_match.groups()[0].lower() == 'y'

    # The firewall is not enabled by default.
    return False


def run(*args):
    p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    rc = p.wait()
    if rc != 0:
        return False, None
    else:
        o = list(map(lambda s: s.decode('utf-8').strip(), p.stdout.read()))
        return True, o


def RunTest():
    UpdateState("TestRunning")
    if not is_firewall_enabled():
        RunLog.info("The firewall is not enabled, skipping checks")
        ResultLog.info('PASS')
        UpdateState("TestCompleted")
        return

    try:
        with open(WIRESERVER_ENDPOINT_FILE, 'r') as f:
            wireserver_ip = f.read()
    except Exception as e:
        RunLog.error("unable to read wireserver ip: {0}".format(e))
        ResultLog.error('FAIL')
        UpdateState("TestCompleted")
        return

    try:
        uid = pwd.getpwnam(FIREWALL_USER)[2]
        os.seteuid(uid)
    except Exception as e:
        RunLog.error("Error -- failed to switch users: {0}".format(e))
        ResultLog.error('FAIL')
        UpdateState("TestCompleted")
        return

    try:
        client = httpclient.HTTPConnection(wireserver_ip, timeout=1)
    except Exception as e:
        RunLog.error("Error -- failed to create HTTP connection: {0}".format(e))
        ResultLog.error('FAIL')
        UpdateState("TestCompleted")
        return

    try:
        client.request('GET', VERSIONS_PATH)
        success = True
    except Exception as e:
        RunLog.error("Error -- failed to connect to wireserver: {0}".format(e))
        success = False

    if success:
        RunLog.error("Error -- user could connect to wireserver")
        ResultLog.error('FAIL')
        UpdateState("TestCompleted")
        return

    RunLog.info("Success -- user access to wireserver is blocked")
    ResultLog.info('PASS')

    # Set current user back, otherwise no permission to write state.txt file
    try:
        uid = pwd.getpwnam(EXECUTION_USER)[2]
        os.seteuid(uid)
    except Exception as e:
        RunLog.error("Error -- failed to switch users: {0}".format(e))
        ResultLog.error('FAIL')
        UpdateState("TestCompleted")
        return

    UpdateState("TestCompleted")

RunTest()
