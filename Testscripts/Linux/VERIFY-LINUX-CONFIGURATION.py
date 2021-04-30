#!/usr/bin/python
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
from azuremodules import *
import os
import os.path

root_bash_hist_file = '/root/.bash_history'
root_bash_hist_file_default = '/root/default_bash_history'

users_password_verify_result = False
sshd_config_check_result = False
last_console_check_result = False
bash_history_verify_result = False
irqbalance_verify_result = False


'''
sshdFilePath = "/etc/ssh/sshd_config"
expectedString = "ClientAliveInterval"
commentedLine = "#ClientAliveInterval"
'''


def IsBashHistFileEmpty(file):
    if os.stat(file).st_size == 0:
        return True, ''
    else:
        with open(file, 'r') as f:
            return False, f.read()


def VerifySSHDConfig():
    global sshd_config_check_result
    RunLog.info("Checking ClientAliveInterval is into the /etc/ssh/sshd_config file")
    ClientAliveIntervalLines = Run("cat /etc/ssh/sshd_config | grep -i '^ClientAliveInterval' | wc -l | tr -d ' ' | tr -d '\n'")
    CommentClientAliveIntervalLines = Run("cat /etc/ssh/sshd_config | grep -i '^#ClientAliveInterval' | wc -l | tr -d ' ' | tr -d '\n'")

    if (int(CommentClientAliveIntervalLines) != 0):
        print ("CLIENT_ALIVE_INTERVAL_COMMENTED")
        RunLog.info("Commented ClientAliveInterval found in /etc/ssh/sshd_config and continue to check the expected interval.")

    if (int(ClientAliveIntervalLines) != 1 ):
        print ("CLIENT_ALIVE_INTERVAL_FAIL")
        RunLog.error('ClientAliveInterval is not into the /etc/ssh/sshd_config file.')
    else:
        RunLog.info("ClientAliveInterval is into in /etc/ssh/sshd_config.")
        RunLog.info("Checking the interval.")
        ClientAliveIntervalValue = Run("cat /etc/ssh/sshd_config | grep -i '^ClientAliveInterval' | awk '{print $2}'")
        if (int(ClientAliveIntervalValue) < 181 and int(ClientAliveIntervalValue) > 0):
            print ("CLIENT_ALIVE_INTERVAL_SUCCESS")
            RunLog.info("ClientAliveInterval " + 'is ' + ClientAliveIntervalValue)
            sshd_config_check_result = True
        else:
            print ("CLIENT_ALIVE_INTERVAL_FAIL")
            RunLog.error("ClientAliveInterval is " + ClientAliveIntervalValue + " is not expected.")


def VerifyUsersPassword():
    global users_password_verify_result
    RunLog.info("Checking if users (except for current user) password is deleted or not...")
    current_user = os.getenv("SUDO_USER")
    RunLog.info('Current user is %s.' % current_user)
    passwd_outputs = Run("cat /etc/shadow | grep -v %s" % current_user)
    for passwd_raw_output in passwd_outputs.splitlines():
        user_passwd = passwd_raw_output.split(":")[1]
        user_name = passwd_raw_output.split(":")[0]
        if ('*' in user_passwd or '!' in user_passwd):
            RunLog.info('user %s password is deleted in /etc/shadow.' % user_name)
            users_password_verify_result = True
        else:
            RunLog.error('user %s password is not deleted.' % user_name)
            users_password_verify_result = False
            print ("USERS_PASSWORD_CHECK_FAIL")
            return
    print ("USERS_PASSWORD_CHECK_SUCCESS")


def CheckLastConsole(command):
    global last_console_check_result
    RunLog.info("Checking for last console as console=ttys0 in  kernel boot line.")
    output = Run(command)
    if (output and output.rfind(" console=") == output.rfind(" console=ttyS0")) :
        RunLog.info('console=ttys0 is present in kernel boot line as a last console. \nOutput:' + output)
        last_console_check_result = True
    else:
        RunLog.error('console=ttys0 is not present in kernel boot line as a last console.')


def VerifyBashHistory():
    global bash_history_verify_result
    if os.path.exists(root_bash_hist_file_default):
        RunLog.info("This is a prepared image, check the copied default history file: %s" % root_bash_hist_file_default)
        result, hist_file_content = IsBashHistFileEmpty(root_bash_hist_file_default)
    elif os.path.exists(root_bash_hist_file):
        RunLog.info("This is a unprepared image, check the original history file: %s" % root_bash_hist_file)
        result, hist_file_content = IsBashHistFileEmpty(root_bash_hist_file)
    else:
        RunLog.info("No bash history file exists.")
        result = True

    if result:
        bash_history_verify_result = True
        RunLog.info("Empty, as expected.")
    else:
        RunLog.error("Not empty, non-expected.")
        RunLog.info("Content:\n%s" % hist_file_content)


def VerifyIrqbalanceExist():
    global irqbalance_verify_result
    result = Run("command -v irqbalance")
    if (result == ''):
        print ("IRQBALANCE_CHECK_FAIL")
        RunLog.error("irqbalance doesn't exist.")
    else:
        irqbalance_verify_result = True
        print ("IRQBALANCE_CHECK_PASS")
        RunLog.info("irqbalance exists.")


def RunTest():
    UpdateState("TestRunning")
    VerifySSHDConfig()
    VerifyUsersPassword()
    CheckLastConsole("dmesg | grep -i 'Kernel command line' | grep -i ' console='")
    VerifyBashHistory()
    VerifyIrqbalanceExist()

    if (users_password_verify_result and sshd_config_check_result and last_console_check_result and bash_history_verify_result and irqbalance_verify_result):
        ResultLog.info('PASS')
    else:
        ResultLog.info('FAIL')

    UpdateState("TestCompleted")


RunTest()
