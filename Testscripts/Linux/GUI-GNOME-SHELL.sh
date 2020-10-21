#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

# This script verifies gnome-shell process in running or not

UTIL_FILE="./utils.sh"

# Source utils.sh
. ${UTIL_FILE} || {
		echo "ERROR: unable to source ${UTIL_FILE}!"
		echo "TestAborted" > state.txt
		exit 0
}

# Source constants file and initialize most common variables
UtilsInit

# Script start from here
LogMsg "*********INFO: Script Execution Started********"

target=$(systemctl get-default)
if [ "${target}" != "graphical.target" ]; then
	LogMsg "Skip test case since VM does not set graphical as default target"
	SetTestStateSkipped
	exit 0
fi

ps -aux | grep "gnome-shell" | grep -v grep

if [ $? -eq 0 ]; then
	LogMsg "Find the gnome-shell process after VM boots up"
	SetTestStateCompleted
	exit 0
else
	LogErr "ERROR: Fail to find the gnome-shell process, maybe GUI cannot login"
	SetTestStateFailed
	exit 1
fi
