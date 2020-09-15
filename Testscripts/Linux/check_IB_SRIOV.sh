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
		LogMsg "Could not determine VM type is either HPC or non-HPC."
		SetTestStateFailed
		exit 0
	fi

	if [ $_type == "2" ]; then
		LogMsg "This VM is non-HPC VM. No further testing."
		SetTestStateAborted
		exit 0
	fi

	if [ $_type == "0" ] || [ $_type == "1" ]; then
		LogMsg "This is HPC VM. Check out the waagent config parameter - OS.EnableRDMA"
		output=$(cat /etc/waagent.conf | grep ^OS.EnableRDMA=y)
		if [ $output == "OS.EnableRDMA=y" ]; then
			LogMsg "Verified waagent config OS.EnableRDMA=y set successfully"
		else
			LogErr "Found waagent configuration of OS.EnableRDMA=y was missing or commented out"
			SetTestStateFailed
			exit 0
		fi

		if [ $_type == "0" ]; then
			LogMsg "This VM has IB over ND. Check out the ND driver files."
			m=$(echo $DISTRO_VERSION | cut -d "." -f 1)
			n=$(echo $DISTRO_VERSION | cut -d "." -f 2)
			if [ -d /opt/microsoft/rdma/rhel$m$n/ ]; then
				LogMsg "Verified Microsoft ND driver in /opt/microsoft/rdma/rhel$m$n"
			else
				LogErr "Failed to find ND driver in /opt/microsoft/rdma/"
				SetTestStateFailed
				exit 0
			fi
		fi

		if [ $_type == "1" ]; then
			LogMsg "The waagent detects IB over SR-ION because of no Nd driver version. Verify it loads inbox or MLX out-of-tree driver loading for IB interface"
			output=$(dmesg | grep 'Mellanox Connect-IB Infiniband driver')
			if [ -z "$output" ]; then
				LogErr "Failed to find SR-IOV driver for IB interface"
				SetTestStateFailed
				exit 0
			else
				LogMsg "Successfully found the SR-IOV driver for IB interface - $output"
			fi
		fi
	fi

}

# main body
Main
SetTestStateCompleted
exit 0