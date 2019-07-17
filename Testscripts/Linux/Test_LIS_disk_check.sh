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
		lis_tarball_name=${lis_tarball_link##*/}
		install_package wget
		LogMsg "Downloading $lis_tarball_link"
		wget $lis_tarball_link
		LogMsg "Extracting $lis_tarball_name ..."
		tar xzf $lis_tarball_name
		# Skip test if LIS does not support kernel version
		pushd LISISO
		./install.sh > install_lis.log
		grep -i "Unsupported kernel version" install_lis.log
		if [ $? -eq 0 ]; then
			LogMsg "Unsupported kernel version. Current kernel version: $(uname -r). Skipping."
			SetTestStateSkipped
			exit 0
		fi
		cleanup
		LogMsg "Now removing LIS..."
		./uninstall.sh
		total_hyperv_packages=$(rpm -qa | grep "hyper-v" | wc -l)
		if [ $total_hyperv_packages -eq 0 ]; then
			LogMsg "LIS not found. (As expected)"
		else
			LogMsg "Error: Found $total_hyperv_packages hyper-v packages installed"
			SetTestStateFailed
			exit 0
		fi
		popd
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
	cleanup
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
			SetTestStateFailed
			exit 0
		fi
	fi
	cd ..
}

cleanup(){
	[ -f /lib/modules/file.out ] && rm -f /lib/modules/file.out
	[ -f /boot/file.out ] && rm -f /boot/file.out
	LogMsg "Cleanup completed."
}

RunTest() {
	distro_package_name=RPMS
	lib_module_folder="/lib/modules"
	boot_folder="/boot"
	MIN_SPACE_FOR_RAMFS_CREATION=157286400   #fetched from spec
	MIN_SZ_ROOT_PARTITION_NON_ROOT=9437184	 #9MB to hit rpm limit
	ROOT_PARTITION_BUFFER_SPACE=10485760     #10MB for log file creation
	BOOT_PARTITION_BUFFER_SPACE=1048576      #allowed limit of +- 1MB

	test_type=$1
	distro_version=$(detect_linux_distribution_version)
	distro_version=$(echo $distro_version | cut -d. -f1,2 | tr -d .)
	LogMsg "DISTRO PACKAGE NAME: $distro_package_name DISTRO VERSION: $distro_version"

	root_partition=$(df -P $lib_module_folder | grep -v Used | awk '{ print $1}')
	boot_partition=$(df -P $boot_folder | grep -v Used | awk '{ print $1}')
	LogMsg "boot_partition $boot_partition - root_partition $root_partition"

	ramdisk_size_factor=1
	[ $root_partition != $boot_partition ] && ramdisk_size_factor=2
	lib_module_required_space=$(rpm --queryformat='%{SIZE}' -qp  LISISO/${distro_package_name}${distro_version}/kmod-microsoft-hyper*x86_64.rpm)
	ramdisk_required_space=$(stat /boot/initramfs-$(uname -r).img --format="%s")
	boot_part_required_space=$(expr $ramdisk_required_space + $BOOT_PARTITION_BUFFER_SPACE)
	root_part_required_space=$(expr $MIN_SPACE_FOR_RAMFS_CREATION + $ramdisk_size_factor \* $ramdisk_required_space + $lib_module_required_space + $ROOT_PARTITION_BUFFER_SPACE)

	# Synchronize to flush all pending writes to disk
	sync

	fblock_non_root=$(($(stat -f --format="%a" $lib_module_folder)))
	fblock_root=$(($(stat -f --format="%f" $lib_module_folder)))

	boot_part_avail_space=$(($(stat -f --format="%f*%S" $boot_folder)))
	root_part_avail_space=$(($(stat -f --format="%a*%S" $lib_module_folder)))

	LogMsg "ramdisk_size_factor $ramdisk_size_factor root_part_avail_space $root_part_avail_space boot_part_avail_space $boot_part_avail_space"
	if [[ $test_type == "negative" ]]; then
		boot_part_required_space=$(expr $boot_part_required_space / 2)
		root_part_required_space=$(expr $root_part_required_space / 2)
		# 6.X distro RPM does not use root user space free space. Hence setting the min limit.
		[[ $fblock_non_root != $fblock_root ]] && root_part_required_space=$MIN_SZ_ROOT_PARTITION_NON_ROOT
	fi

	if [[ $boot_partition == $root_partition ]]; then
		LogMsg "boot and root share the same partition. We will create only one file"
		single_partition_file_size=$(expr $root_part_avail_space - $root_part_required_space)
		LogMsg "single_partition_file_size $single_partition_file_size"
		CreateFile "${single_partition_file_size}" /lib/modules/file.out
		single_partition_created_file_size=$(ls -l /lib/modules/file.out | awk '{print $5}'  | tail -1)
		LogMsg "single_partition_created_file_size : $single_partition_created_file_size"
		if [[ "$single_partition_created_file_size" == "${single_partition_file_size}" ]]; then
			file_status="created"
		else
			file_status="failed"
		fi
	else
		LogMsg "boot and modules do not share the same partition."
		single_partition_file_size=$(expr $root_part_avail_space - $root_part_required_space)
		single_partition_file_size_boot=$(expr $boot_part_avail_space - $boot_part_required_space)
		LogMsg "file size - root partition: $single_partition_file_size boot partition: $single_partition_file_size_boot"
		CreateFile "${single_partition_file_size}" /lib/modules/file.out
		single_partition_created_file_size=$(ls -l /lib/modules/file.out | awk '{print $5}'  | tail -1)
		CreateFile "${single_partition_file_size_boot}" /boot/file.out
		boot_created_file_size=$(ls -l /boot/file.out | awk '{print $5}'  | tail -1)
		if [[ "$single_partition_file_size" == "${single_partition_created_file_size}"
			&& "$single_partition_file_size_boot" == "${boot_created_file_size}" ]]; then
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
