#!/usr/bin/python

from azuremodules import *
import argparse
import os

parser = argparse.ArgumentParser()
parser.add_argument('-wl', '--whitelist', help='specify the xml file which contains the ignorable errors')

args = parser.parse_args()
white_list_xml = args.whitelist

def RunTest():
    UpdateState("TestRunning")
    RunLog.info("Checking for ERROR and WARNING messages in  kernel boot line.")
    errors = Run("dmesg | grep -i error")
    warnings = Run("dmesg | grep -i warning")
    failures = Run("dmesg | grep -i fail")

    if (not errors and not warnings and not failures):
        RunLog.error('ERROR/WARNING/FAILURE are not present in kernel boot line.')
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
            RunLog.info('ERROR/WARNING/FAILURE are  present in kernel boot line.')
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
