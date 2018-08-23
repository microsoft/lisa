#!/bin/bash

#######################################################################
#
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
#######################################################################

#######################################################################
#
# nested_kvm_basic_test.sh
#
# Description:
#   This script tests the basic functionality of nested VM in a Linux VM, steps:
#     1. Start a nested ubuntu VM, VM network: user mode network, with host port redirect enabled
#     2. Verify the nested VM can access public network, by running a command in the nested VM to download a public file from github
#
# Parameters:
#   -NestedImageUrl: The public url of the nested image, the image format should be qcow2
#   -NestedUser: The user name of the nested image
#   -NestedUserPassword: The user password of the nested image
#   -HostFwdPort: The host port that will redirect to the SSH port of the nested VM
#   -logFolder: The folder path for logs
#
#######################################################################
# Source nested_kvm_utils.sh
. nested_kvm_utils.sh || {
	echo "ERROR: unable to source nested_kvm_utils.sh!"
	echo "TestAborted" > state.txt
	exit 2
}

# Source constants file and initialize most common variables
UtilsInit

while echo $1 | grep -q ^-; do
	declare $( echo $1 | sed 's/^-//' )=$2
	shift
	shift
done

ImageName="nested.qcow2"

if [ -z "$NestedImageUrl" ]; then
	echo "Please mention -NestedImageUrl next"
	exit 1
fi
if [ -z "$HostFwdPort" ]; then
	echo "Please mention -HostFwdPort next"
	exit 1
fi
if [ -z "$NestedUser" ]; then
	echo "Please mention -NestedUser next"
	exit 1
fi
if [ -z "$NestedUserPassword" ]; then
	echo "Please mention -NestedUserPassword next"
	exit 1
fi
if [ -z "$logFolder" ]; then
	logFolder="."
	echo "-logFolder is not mentioned. Using ."
else
	echo "Using Log Folder $logFolder"
fi

test_nested_vm()
{
	#Prepare command for start nested kvm
	cmd="qemu-system-x86_64 -smp 2 -m 2048 -hda $ImageName -display none -device e1000,netdev=user.0 -netdev user,id=user.0,hostfwd=tcp::$HostFwdPort-:22 -enable-kvm -daemonize"
	#Start nested kvm
	start_nested_vm -user $NestedUser -passwd $NestedUserPassword -port $HostFwdPort $cmd
}



install_kvm_dependencies
download_image_files -destination_image_name $ImageName -source_image_url $NestedImageUrl

#Prepare nested kvm
test_nested_vm
stop_nested_vm
SetTestStateCompleted

#Exiting with zero is important.
exit 0