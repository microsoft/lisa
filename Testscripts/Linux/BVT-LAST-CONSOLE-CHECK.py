#!/usr/bin/python

from azuremodules import *

def RunTest(command):
    UpdateState("TestRunning")
    RunLog.info("Checking for last console as console=ttys0 in  kernel boot line.")
    output = Run(command)
    if (output and output.rfind(" console=") == output.rfind(" console=ttyS0")) :
        RunLog.info('console=ttys0 is present in kernel boot line as a last console. \nOutput:' + output)
        ResultLog.info('PASS')
        UpdateState("TestCompleted")
    else :
        RunLog.error('console=ttys0 is not present in kernel boot line as a last console.')
        ResultLog.error('FAIL')
        UpdateState("TestCompleted")

RunTest("dmesg | grep -i 'Kernel command line' | grep -i ' console='")
