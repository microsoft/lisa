#!/usr/bin/env python
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
from azuremodules import *
from subprocess import Popen, PIPE
from collections import OrderedDict
import sys
import platform
import string
import random

file_path = os.path.dirname(os.path.realpath(__file__))
constants_path = os.path.join(file_path, "constants.sh")
params = GetParams(constants_path)
origin_password = params["PASSWORD"]

allowed_min_len_passwd = 6
allowed_max_len_passwd = 72

# test points
#1 password is too short but obey the complexity
#2 password is too long but obey the complexity
#3 password is too simplistic but valid length
#4 password obey the policy complexity
#   a) a lowercase character
#   b) an uppercase character
#   c) a number
#   d) a special character 

def DetectDist():
	return [x.strip() for x in platform.linux_distribution()]

def DetectSLESServicePatch():
	patchlevel = None
	if os.path.exists('/etc/SuSE-release'):
		with open('/etc/SuSE-release','r') as f:
			for x in f.readlines():
				if x.startswith('PATCHLEVEL'):
					patchlevel = x.split('=')[1].strip()
	return patchlevel

def GenRandomPassword(pcomplexity,plength=6):
	passwd_length = int(plength)
	nums = range(0,10)
	lowercases = tuple(string.ascii_lowercase)
	uppercases = tuple(string.ascii_uppercase)
	special_chars = ('#','!','^')
	password_matrix = (nums, lowercases, uppercases, special_chars)
	random_rules = random.sample(password_matrix,pcomplexity)
	newpass = ""
	for x in random_rules:
		newpass += str(random.choice(x))
	# filling 
	while passwd_length-len(newpass):
		index = pcomplexity-1
		new_char = str(random.choice(random_rules[random.randint(0,index)]))
		# fix issue of the random password which does not contain enough DIFFERENT characters
		if new_char not in newpass:
			newpass += new_char
	return newpass

def ResetPassword(currentpassword,):
	proc = Popen(['passwd'],stdin=PIPE,stdout=PIPE,stderr=PIPE)
	out = proc.communicate(currentpassword+'\n'+origin_password+'\n'+origin_password+'\n')
	rtc = proc.returncode
	if int(rtc) == 0:
		RunLog.info('reset password succesfully after test.')
		return True
	else:
		RunLog.error('reset password failed after test.')
		return False

def RunTest():
	UpdateState("TestRunning")
	# define test matrix
	test_matrix_password = OrderedDict()
	test_matrix_password['pwd_too_short'] = ('123', False)
	test_matrix_password['pwd_only_lowercase'] = ('abcdef', False)
	test_matrix_password['pwd_only_uppercase'] = ('HELLOTEST', False)
	test_matrix_password['pwd_only_number'] = ('123456', False)
	test_matrix_password['pwd_random_2_rules'] = (GenRandomPassword(2), False)
	test_matrix_password['pwd_random_3_rules'] = (GenRandomPassword(3), True)
	test_matrix_password['pwd_random_4_rules'] = (GenRandomPassword(4), True)

	dist, ver, _ = DetectDist()
	failure = 0
	if dist.upper() == "COREOS":
		RunLog.info('CoreOS is not supported in automation by now. Still in investigation, now mark with PASS')	
	elif (dist == "SUSE Linux Enterprise Server" and ver == "12" and DetectSLESServicePatch() == '1') or dist == "Red Hat Enterprise Linux Server":
		for t,p in test_matrix_password.items():
			RunLog.info('Part: %s' % t)
			if(ChangePwd(p[0]) == p[1]):
				RunLog.info("%s_CHECK: PASS with password: %s" % (t, p[0]))
			else:
				RunLog.error("%s_CHECK: FAIL with password: %s" % (t,p[0]))
				failure += 1
			RunLog.info('')
	# will adjust automation of other distro in future
	else:
		RunLog.info('Will adjust automation of other distro according to their characteristic in future, now mark with PASS')
	
	if not failure:
		ResultLog.info('PASS') 
	else:
		ResultLog.info('FAIL') 
	UpdateState("TestCompleted")

def ChangePwd(newpassword):
	proc = Popen(['passwd'],stdin=PIPE,stdout=PIPE,stderr=PIPE)
	out = proc.communicate(origin_password+'\n'+newpassword+'\n'+newpassword+'\n')
	rtc = proc.returncode
	RunLog.info('Output Message:')
	RunLog.info(out)
	if int(rtc) == 0:
		ResetPassword(newpassword)
		return True
	else:
		return False

RunTest()
