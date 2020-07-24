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
#     2. Verify to be able to copy files from the L1 host to the nested VM, by scp constants.sh to the nested VM
#     3. Verify the nested VM can access public network, by running a command in the nested VM to download a public file from github
#
# Parameters:
#   -NestedImageUrl: The public url of the nested image, the image format should be qcow2
#   -NestedUser: The user name of the nested image
#   -NestedUserPassword: The user password of the nested image
#   -HostFwdPort: The host port that will redirect to the SSH port of the nested VM
#   -logFolder: The folder path for logs
#
#######################################################################
# Source nested_vm_utils.sh
. nested_vm_utils.sh || {
	echo "ERROR: unable to source nested_vm_utils.sh!"
	echo "TestAborted" > state.txt
	exit 0
}

# Source constants file and initialize most common variables
UtilsInit

case "$DISTRO" in
	redhat_6)
		LogMsg "Not support in RHEL-6. Skip."
		SetTestStateSkipped
		exit 0
		;;
esac

while echo "$1" | grep -q ^-; do
	declare $( echo "$1" | sed 's/^-//' )=$2
	shift
	shift
done

ImageName="nested.qcow2"

if [ -z "$NestedImageUrl" ]; then
	LogErr "Missing the required parameter -NestedImageUrl. Test Aborted"
	SetTestStateAborted
	exit 0
fi
if [ -z "$HostFwdPort" ]; then
	LogErr "Missing the required parameter -HostFwdPort. Test Aborted"
	SetTestStateAborted
	exit 0
fi
if [ -z "$NestedUser" ]; then
	LogErr "Missing the required parameter -NestedUser. Test Aborted"
	SetTestStateAborted
	exit 0
fi
if [ -z "$NestedUserPassword" ]; then
	LogErr "Missing the required parameter -NestedUserPassword. Test Aborted"
	SetTestStateAborted
	exit 0
fi
if [ -z "$logFolder" ]; then
	logFolder="."
	LogMsg "-logFolder is not mentioned. Using ."
else
	LogMsg "Using Log Folder $logFolder"
fi

Test_Nested_VM()
{
	#Prepare command for start nested kvm
	cmd="qemu-system-x86_64 -smp 2 -m 2048 -hda /mnt/resource/$ImageName -display none -device e1000,netdev=user.0 -netdev user,id=user.0,hostfwd=tcp::$HostFwdPort-:22 -enable-kvm -daemonize"
	#Start nested kvm
	Start_Nested_VM -user "$NestedUser" -passwd "$NestedUserPassword" -port "$HostFwdPort" "$cmd"
	#Verify copying file from L1 host to nested VM
	Verify_Host_Connection -user "$NestedUser" -passwd "$NestedUserPassword" -port "$HostFwdPort"
	#Verify downloading a file from Internet to the nested VM
	Verify_External_Connection -user "$NestedUser" -passwd "$NestedUserPassword" -port "$HostFwdPort"
}

Install_KVM_Dependencies
Download_Image_Files -destination_image_name $ImageName -source_image_url "$NestedImageUrl"

#Prepare nested kvm
Test_Nested_VM
Stop_Nested_VM
SetTestStateCompleted

#Exiting with zero is important.
exit 0