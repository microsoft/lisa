#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
# 
#
# Sample script to run sysbench.
# In this script, we want to bench-mark device IO performance on a mounted folder.
# You can adapt this script to other situations easily like for stripe disks as RAID0.
# The only thing to keep in mind is that each different configuration you're testing
# must log its output to a different directory.
#

LogMsg()
{
	echo "[$(date +"%x %r %Z")] ${1}"
	echo "[$(date +"%x %r %Z")] ${1}" >> "./TestExecution.log"
}

UpdateTestState()
{
	echo "${1}" > ./TestState.log
}

############################################################
#	Main body
############################################################

LogMsg "*********INFO: Starting test execution ... *********"
OUTPUT="$(lspci)"
LogMsg "${OUTPUT}"

lspci | grep -i "Mellanox"

if [[ "$?" == "0" ]];
then
	UpdateTestState "PASS"
else
	UpdateTestState "FAIL"
fi

LogMsg "*********INFO: Script execution completed. *********"
exit 0