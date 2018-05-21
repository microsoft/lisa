#!/usr/bin/python

from azuremodules import *
import re

'''
sshdFilePath = "/etc/ssh/sshd_config" 
expectedString = "ClientAliveInterval"
commentedLine = "#ClientAliveInterval"
'''

def RunTest():
	UpdateState("TestRunning")
	RunLog.info("Checking ClientAliveInterval is into the /etc/ssh/sshd_config file")
	ClientAliveIntervalLines = Run("cat /etc/ssh/sshd_config | grep -i '^ClientAliveInterval' | wc -l | tr -d ' ' | tr -d '\n'")
	CommentClientAliveIntervalLines = Run("cat /etc/ssh/sshd_config | grep -i '^#ClientAliveInterval' | wc -l | tr -d ' ' | tr -d '\n'")

	if (int(CommentClientAliveIntervalLines) != 0):
		print ("CLIENT_ALIVE_INTERVAL_COMMENTED")
		RunLog.info("Commented ClientAliveInterval found in /etc/ssh/sshd_config and continue to check the expected interval.")

	if (int(ClientAliveIntervalLines) != 1 ):
		print ("CLIENT_ALIVE_INTERVAL_FAIL")
		RunLog.error('ClientAliveInterval is not into the /etc/ssh/sshd_config file.')
		ResultLog.error('FAIL')
	else:
		RunLog.info("ClientAliveInterval is into in /etc/ssh/sshd_config.")
		RunLog.info("Checking the interval.")
		ClientAliveIntervalValue = Run("cat /etc/ssh/sshd_config | grep -i '^ClientAliveInterval' | awk '{print $2}'")
		if (int(ClientAliveIntervalValue) < 181 and int(ClientAliveIntervalValue) > 0):
			print ("CLIENT_ALIVE_INTERVAL_SUCCESS")
			RunLog.info("ClientAliveInterval " + 'is ' + ClientAliveIntervalValue)
			ResultLog.info('PASS')
		else:
			print ("CLIENT_ALIVE_INTERVAL_FAIL")
			RunLog.error("ClientAliveInterval is " + ClientAliveIntervalValue + " is not expected.")
			ResultLog.info('FAIL')
	UpdateState("TestCompleted")

RunTest()