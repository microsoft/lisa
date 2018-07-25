#!/bin/bash

########################################################################
#
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
########################################################################
########################################################################
#
# Description:
#	This script installs NVidia GPU drivers.
#
#	Steps:
#	1. Installs dependencies
#	2. Compiles and installs GPU Drievers
#	3. -logFolder parameter is supported (Optional)
#	
#
########################################################################

while echo $1 | grep ^- > /dev/null; do
	eval $( echo $1 | sed 's/-//g' | tr -d '\012')=$2
	shift
	shift
done

#Updated as of 23rd May 2018
CUDADriverVersion="9.2.88-1"
#############################


ICA_TESTRUNNING="TestRunning"	  # The test is running
ICA_TESTCOMPLETED="TestCompleted"  # The test completed successfully
ICA_TESTABORTED="TestAborted"	  # Error during setup of test
ICA_TESTFAILED="TestFailed"		# Error while performing the test"

if [ ! ${logFolder} ]; then
	logFolder="/root"
fi

#######################################################################
# Adds a timestamp to the log file
#######################################################################
LogMsg() {
	echo $(date "+%a %b %d %T %Y") : ${1}
	echo $(date "+%a %b %d %T %Y") : ${1} >> $logFolder/GPU_Test_Logs.txt 
}

#######################################################################
# Updates the summary.log file
#######################################################################
UpdateSummary() {
	echo $1 >> $logFolder/summary.log
}

#######################################################################
# Keeps track of the state of the test
#######################################################################
UpdateTestState() {
	echo $1 > $logFolder/state.txt
}

#######################################################################
# Install dependencies and GPU Driver
#######################################################################
InstallGPUDrivers() {
		DISTRO=`grep -ihs "buntu\|Suse\|Fedora\|Debian\|CentOS\|Red Hat Enterprise Linux" /etc/{issue,*release,*version}`

		if [[ $DISTRO =~ "Ubuntu 16.04" ]];
		then
				LogMsg "Detected UBUNUT1604"
				CUDA_REPO_PKG="cuda-repo-ubuntu1604_${CUDADriverVersion}_amd64.deb"
				LogMsg "Using ${CUDA_REPO_PKG}"
				wget http://developer.download.nvidia.com/compute/cuda/repos/ubuntu1604/x86_64/${CUDA_REPO_PKG} -O /tmp/${CUDA_REPO_PKG}
				dpkg -i /tmp/${CUDA_REPO_PKG}
				rm -f /tmp/${CUDA_REPO_PKG}
				until dpkg --force-all --configure -a; sleep 10; do echo 'Trying again...'; done
				apt-get -y update
				apt-get -y --allow-unauthenticated install linux-tools-generic linux-cloud-tools-generic
				apt-get -y --allow-unauthenticated install cuda-drivers
								
		elif [[ $DISTRO =~ "Ubuntu 14.04" ]];
		then
				LogMsg "Detected UBUNTU1404"
				CUDA_REPO_PKG="cuda-repo-ubuntu1404_${CUDADriverVersion}_amd64.deb"
				LogMsg "Using ${CUDA_REPO_PKG}"				
				wget http://developer.download.nvidia.com/compute/cuda/repos/ubuntu1404/x86_64/${CUDA_REPO_PKG} -O /tmp/${CUDA_REPO_PKG}
				dpkg -i /tmp/${CUDA_REPO_PKG}
				rm -f /tmp/${CUDA_REPO_PKG}
				apt-get -y update
				apt-get -y --allow-unauthenticated install linux-tools-generic linux-cloud-tools-generic
				apt-get -y --allow-unauthenticated install cuda-drivers
				
		elif [[ $DISTRO =~ "CentOS Linux release 7.3" ]] || [[ $DISTRO =~ "CentOS Linux release 7.4" ]] || [[ $DISTRO =~ "Red Hat Enterprise Linux Server release 7.4" ]];
		then
				LogMsg "Detected CentOS 7.x / RHEL 7.x"
				sed -i "/^exclude=kernel/c\#exclude=kernel*" /etc/yum.conf
				yum -y update
				yum -y --nogpgcheck install kernel-devel
				rpm -Uvh https://dl.fedoraproject.org/pub/epel/epel-release-latest-7.noarch.rpm				
				yum --nogpgcheck -y install dkms
				CUDA_REPO_PKG="cuda-repo-rhel7-${CUDADriverVersion}.x86_64.rpm"
				LogMsg "Using ${CUDA_REPO_PKG}"					
				wget http://developer.download.nvidia.com/compute/cuda/repos/rhel7/x86_64/${CUDA_REPO_PKG} -O /tmp/${CUDA_REPO_PKG}
				rpm -ivh /tmp/${CUDA_REPO_PKG}
				rm -f /tmp/${CUDA_REPO_PKG} 
				yum --nogpgcheck -y install lshw
				yum --nogpgcheck -y install cuda-drivers
		else
				LogMsg "Unknown Distro"
				UpdateTestState "TestAborted"
				UpdateSummary "Unknown Distro, test aborted"
				return 1
		fi
}

######################################################################
#MAIN
######################################################################

LogMsg "Updating test case state to running"
UpdateTestState $ICA_TESTRUNNING
InstallGPUDrivers
if [[ $? == 0 ]];
then
	LogMsg "GPU_DRIVER_INSTALLATION_SUCCESSFUL"
else
	LogMsg "GPU_DRIVER_INSTALLATION_FAIL"
fi
UpdateTestState $ICA_TESTCOMPLETED
exit 0
