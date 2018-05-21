#!/usr/bin/python

from azuremodules import *

def RunTest():
    UpdateState("TestRunning")
    if (IsUbuntu()) :
        mntresource = "/mnt/"
    else :
        mntresource = "/mnt/resource/"
    RunLog.info("Checking README is created in " + mntresource)
    matchString = "'Any data stored on this drive is SUBJECT TO LOSS'"
    matchCount = Run("grep -i " + matchString + " " + mntresource + "DATALOSS_WARNING_README.txt | wc -l")
    if matchCount != 0 :
        RunLog.info("README file is successfully created in " + mntresource)
        ResultLog.info('PASS')
        UpdateState("TestCompleted")
    else :
        RunLog.error("README file is not successfully created in " + mntresource)
        ResultLog.error('FAIL')
        UpdateState("TestCompleted")

RunTest()