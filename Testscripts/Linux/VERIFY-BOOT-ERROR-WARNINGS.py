#!/usr/bin/python
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
from azuremodules import *
from shutil import copyfile

white_list_xml = "ignorable-boot-errors.xml"
wala_white_list_xml = "ignorable-walalog-errors.xml"
logfile_list = [
    "/var/log/syslog",
    "/var/log/messages",
    "/tmp/dmesg"
]


def _filter_log(keyword):
    return Run("grep -nw '{}.*' {} --ignore-case --no-message".format(
        keyword, ' '.join(logfile_list))).strip().split('\n')


def RunTest():
    UpdateState("TestRunning")
    Run("dmesg > /tmp/dmesg")
    RunLog.info(
        "Checking for ERROR/WARNING/FAILURE messages in system logs:{}".format(
            logfile_list))
    errors = _filter_log('err')
    warnings = _filter_log('warn')
    failures = _filter_log('fail')
    if (not errors and not warnings and not failures):
        RunLog.info(
            'Could not find ERROR/WARNING/FAILURE messages in system log files.')
        ResultLog.info('PASS')
    else:
        if white_list_xml and os.path.isfile(white_list_xml):
            try:
                import xml.etree.cElementTree as ET
            except ImportError:
                import xml.etree.ElementTree as ET

            white_list_file = ET.parse(white_list_xml)
            xml_root = white_list_file.getroot()

            wala_white_list_file = ET.parse(wala_white_list_xml)
            wala_xml_root = wala_white_list_file.getroot()

            RunLog.info(
                'Checking ignorable boot ERROR/WARNING/FAILURE messages...')
            for node in xml_root:
                if (failures and node.tag == "failures"):
                    failures = RemoveIgnorableMessages(failures, node)
                if (errors and node.tag == "errors"):
                    errors = RemoveIgnorableMessages(errors, node)
                if (warnings and node.tag == "warnings"):
                    warnings = RemoveIgnorableMessages(warnings, node)

            RunLog.info(
                'Checking ignorable wala ERROR/WARNING/FAILURE messages...')
            for node in wala_xml_root:
                if failures:
                    failures = RemoveIgnorableMessages(failures, node)
                if errors:
                    errors = RemoveIgnorableMessages(errors, node)
                if warnings:
                    warnings = RemoveIgnorableMessages(warnings, node)

        if (errors or warnings or failures):
            RunLog.error('Found ERROR/WARNING/FAILURE messages in logs.')
            if(errors):
                SplitLog('Errors', errors)
            if(warnings):
                SplitLog('warnings', warnings)
            if(failures):
                SplitLog('failures', failures)
            ResultLog.error('FAIL')
        else:
            ResultLog.info('PASS')
    UpdateState("TestCompleted")
    CollectLogs()


def SplitLog(logType, logValues):
    for logEntry in logValues:
        RunLog.info(logType + ': ' + logEntry)


def RemoveIgnorableMessages(message_list, keywords_xml_node):
    valid_list = []
    for msg in message_list:
        for keywords in keywords_xml_node:
            if re.findall(keywords.text, msg, re.M):
                RunLog.info('Ignorable ERROR/WARNING/FAILURE message: ' + msg)
                break
        else:
            valid_list.append(msg)
    if len(valid_list) > 0:
        return valid_list
    else:
        return None


def CollectLogs():
    logfiles = ['/var/log/messages']
    hostname = os.uname()[1]
    for logfile in logfiles:
        if os.path.exists(logfile):
            dst = "{}/{}{}.txt".format(os.getcwd(), hostname,
                                       logfile.replace('/', '-'))
            try:
                RunLog.info("Copying {} to {}...".format(logfile, dst))
                copyfile(logfile, dst)
            except Exception:
                RunLog.warn("Copy {} to {} failed!".format(logfile, dst))
    RunLog.info("Copy all logs finished!")


RunTest()
