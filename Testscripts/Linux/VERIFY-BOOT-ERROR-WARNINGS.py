#!/usr/bin/python
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
from azuremodules import *

white_list_xml = "ignorable-boot-errors.xml"


def RunTest():
    UpdateState("TestRunning")
    RunLog.info("Checking for ERROR and WARNING messages in system logs.")
    errors = Run("grep -nw '/var/log/syslog' -e 'error' --ignore-case && grep -nw '/var/log/messages' -e 'error' --ignore-case")
    warnings = Run("grep -nw '/var/log/syslog' -e 'warning' --ignore-case && grep -nw '/var/log/messages' -e 'warning' --ignore-case")
    failures = Run("grep -nw '/var/log/syslog' -e 'fail' --ignore-case && grep -nw '/var/log/messages' -e 'fail' --ignore-case")
    if (not errors and not warnings and not failures):
        RunLog.info('Could not find ERROR/WARNING/FAILURE messages in syslog/messages log file.')
        ResultLog.info('PASS')
    else:
        if white_list_xml and os.path.isfile(white_list_xml):
            try:
                import xml.etree.cElementTree as ET
            except ImportError:
                import xml.etree.ElementTree as ET

            white_list_file = ET.parse(white_list_xml)
            xml_root = white_list_file.getroot()

            RunLog.info('Checking ignorable boot ERROR/WARNING/FAILURE messages...')
            for node in xml_root:
                if (failures and node.tag == "failures"):
                    failures = RemoveIgnorableMessages(failures, node)
                if (errors and node.tag == "errors"):
                    errors = RemoveIgnorableMessages(errors, node)
                if (warnings and node.tag == "warnings"):
                    warnings = RemoveIgnorableMessages(warnings, node)

        if (errors or warnings or failures):
            RunLog.error('Found ERROR/WARNING/FAILURE messages in logs.')
            if(errors):
               RunLog.info('Errors: ' + ''.join(errors))
            if(warnings):
               RunLog.info('warnings: ' + ''.join(warnings))
            if(failures):
               RunLog.info('failures: ' + ''.join(failures))
            ResultLog.error('FAIL')
        else:
            ResultLog.info('PASS')
    UpdateState("TestCompleted")


def RemoveIgnorableMessages(messages, keywords_xml_node):
    message_list = messages.strip().split('\n')
    valid_list = []
    for msg in message_list:
        for keywords in keywords_xml_node:
            if keywords.text in msg:
                RunLog.info('Ignorable ERROR/WARNING/FAILURE message: ' + msg)
                break
        else:
            valid_list.append(msg)
    if len(valid_list) > 0:
        return valid_list
    else:
        return None

RunTest()
