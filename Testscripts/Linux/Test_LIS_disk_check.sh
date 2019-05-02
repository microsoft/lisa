#!/bin/bash

# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

# Description:
# We've added new feature in LIS RPM installation script to check the disk space
#       before proceeding to LIS install.
# This avoids half / corrupted installations.
# This test script executes in two ways -
# Positive scenarios - Test leaves "bare minimum" size avaialble
#       for LIS install and checks if LIS installation is successful.
# Negative scenario - Test leaves "non installable" size on disk and
#       checks if ./install.sh script skips the installation of not.
# Note: This also takes care of additional space required for 7.3 and 7.4 distros.
#	       For this test, we're expecting VHD with no LIS installed.
#	       If LIS is installed, then this script will uninstall it.
##################################################################################

# Source utils.sh
. utils.sh || {
	echo "Error: unable to source utils.sh!"
	echo "TestAborted" > state.txt
	exit 0
}

# Source constants file and initialize most common variables
UtilsInit

PrepareForTest() {
	lis_tarball_link=$1
	distro=$(detect_linux_distribution)
	if [[ $distro == "centos" || $distro == "oracle" || $distro == "rhel" ]]; then
		total_hyperv_packages=$(rpm -qa | grep "hyper-v" | wc -l)
		if [ $total_hyperv_packages -gt 0 ]; then
			hyperv_package_names=$(rpm -qa | grep "hyper-v" | xargs)
			LogMsg "Uninstalling hyperv packages..."
			yum -y remove $hyperv_package_names
			LogMsg "Removed $total_hyperv_packages hyperv packages."
		else
			LogMsg "LIS not found. (As expected)"
		fi
		lis_tarball_name=${lis_tarball_link##*/}
		LogMsg "Downloading $lis_tarball_link"
		wget $lis_tarball_link
		LogMsg "Extracting $lis_tarball_name ..."
		tar xzf $lis_tarball_name
		LogMsg "Ready for the test."
	else
		LogMsg "Unsupported distro. Supported distros: centos, oracle, rhel. Skipping."
		SetTestStateSkipped
		exit 0
	fi
}

Install_Uninstall_LIS() {
	test_type=$1
	cd LISISO
	./install.sh
	if [[ "$test_type" == "positive" ]]; then
		total_hyperv_packages=$(rpm -qa | grep "hyper-v" | wc -l)
		if [ $total_hyperv_packages -gt 0 ]; then
			LogMsg "Found $total_hyperv_packages hyper-v packages installed"
			LogMsg "Now removing LIS..."
			./uninstall.sh
			total_hyperv_packages=$(rpm -qa | grep "hyper-v" | wc -l)
			if [ $total_hyperv_packages -eq 0 ]; then
				LogMsg "Found $total_hyperv_packages hyper-v packages installed"
				LogMsg "Test '$test_type' : PASS"
			else
				LogMsg "Error: Found $total_hyperv_packages hyper-v packages installed"
				LogMsg "Test '$test_type' : FAIL"
				cleanup
				SetTestStateFailed
				exit 0
			fi
		else
			LogMsg "Error: unable to find hyper-v packages"
			LogMsg "Test '$test_type' : FAIL"
			cleanup
			SetTestStateFailed
			exit 0
		fi
	elif [[ "$test_type" == "negative" ]]; then
		total_hyperv_packages=$(rpm -qa | grep "hyper-v" | wc -l)
		if [ $total_hyperv_packages -eq 0 ]; then
			LogMsg "Found $total_hyperv_packages hyper-v packages installed"
			LogMsg "Test '$test_type' : PASS"
		else
			LogMsg "Error: Found $total_hyperv_packages hyper-v packages installed"
			LogMsg "Test '$test_type' : FAIL"
			cleanup
			SetTestStateFailed
			exit 0
		fi
	fi
	cd ..
}

cleanup(){
	cleanup_file_names=$(find / -name file.out | xargs)
	if [[ $cleanup_file_names != "" ]]; then
		LogMsg "Removing $cleanup_file_names ..."
		rm -rf $cleanup_file_names
	fi
	LogMsg "Cleanup completed."
}

RunTest() {
	test_type=$1
	distro=$(detect_linux_distribution)
	distro_version=$(detect_linux_distribution_version)

	if [[ "$distro_version" =~ "7.3" || "$distro_version" =~ "7.4" ]]; then
		modules_safe_data_size=150
	else
		modules_safe_data_size=70
	fi
	boot_safe_data_size=50
	if [[ $test_type == "negative" ]]; then
		modules_safe_data_size=50
		boot_safe_data_size=20
	fi

	LogMsg "modules_safe_data_size: $modules_safe_data_size"
	LogMsg "boot_safe_data_size: $boot_safe_data_size"
	boot_partition=$(df -hm /lib/modules | awk '{print $1}' | tail -1)
	modules_partition=$(df -hm /boot | awk '{print $1}' | tail -1)
	#Check if the disk space is in positive category
	modules_directory_size=$(df -hm /lib/modules | awk '{print $4}'  | tail -1)
	modules_directory_target_size=$(expr $modules_directory_size - $modules_safe_data_size)
	boot_directory_size=$(df -hm /boot | awk '{print $4}'  | tail -1)
	if [[ $boot_partition == $modules_partition ]]; then
		LogMsg "boot and modules share the same partition. We will create only one file"
		single_partition_file_size=$(expr $modules_directory_size - $modules_safe_data_size - $boot_safe_data_size)
	else
		LogMsg "boot and modules do not share the same partition."
		boot_directory_target_size=$(expr $boot_directory_size - $boot_safe_data_size)
	fi

	LogMsg "modules_directory_size: $modules_directory_size"
	LogMsg "modules_directory_target_size: $modules_directory_target_size"
	LogMsg "boot_directory_size : $boot_directory_size"
	LogMsg "boot_directory_target_size: $boot_directory_target_size"
	if [ $single_partition_file_size -gt 0 ]; then
		CreateFile "${single_partition_file_size}M" /lib/modules/file.out
		singe_partition_created_file_size=$(ls -l --block-size=M /lib/modules/file.out | awk '{print $5}'  | tail -1)
		LogMsg "singe_partition_created_file_size : $singe_partition_created_file_size"
		if [[ "$singe_partition_created_file_size" == "${single_partition_file_size}M" ]]; then
			file_status="created"
		else
			file_status="failed"
		fi
	else
		CreateFile "${modules_directory_target_size}M" /lib/modules/file.out
		module_created_file_size=$(ls -l --block-size=M /lib/modules/file.out | awk '{print $5}'  | tail -1)
		CreateFile "${boot_directory_target_size}M" /boot/file.out
		boot_created_file_size=$(ls -l --block-size=M /boot/file.out | awk '{print $5}'  | tail -1)
		if [[ "$module_created_file_size" == "${modules_directory_target_size}M"
			&& "$boot_created_file_size" == "${boot_directory_target_size}M" ]]; then
			file_status="created"
		else
			file_status="failed"
		fi
	fi
	usage=$(df -hm)
	LogMsg "$usage"
	LogMsg "$file_status"
	if [[ $file_status == "created" ]]; then
		Install_Uninstall_LIS $test_type
	else
		if [ $single_partition_file_size -gt 0 ]; then
			LogMsg "Error: singe_partition_created_file_size: $singe_partition_created_file_size"
		else
			LogMsg "Error: module_created_file_size: $module_created_file_size"
			LogMsg "Error: boot_created_file_size: $boot_created_file_size"
		fi
		LogMsg "Error: Unable to run tests. Aborting."
		SetTestStateAborted
		cleanup
		exit 0
	fi
	cleanup
}

PrepareForTest $LIS_TARBALL_URL_CURRENT

RunTest "positive"
RunTest "negative"

SetTestStateCompleted
cleanup
exit 0