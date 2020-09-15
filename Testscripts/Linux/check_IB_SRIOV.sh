#!/bin/bash
#
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
########################################################################################################
# Source utils.sh
. utils.sh || {
	echo "Error: unable to source utils.sh!"
	echo "TestAborted" > state.txt
	exit 0
}
# Source constants file and initialize most common variables
UtilsInit

# Constants/Globals
# Get distro information
GetDistro

function Main() {

	is_hpc_vm
	_type=$?
	if [ $_type == "3" ]; then
		LogMsg "Could not determine VM type is HPC or non-HPC."
		SetTestStateFailed
		exit 0
	fi

	if [ $_type == "2" ]; then
		LogMsg "This VM is non-HPC VM. No further testing."
		SetTestStateAborted
		exit 0
	fi

	if [ $_type == "0" || $_type == "1" ]; then
		LogMsg "This VM is HPC type. Check out "
	

}

# main body
Main
SetTestStateCompleted
exit 0