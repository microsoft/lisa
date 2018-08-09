#!/bin/bash

#######################################################################
#
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
# Description: It install the LIS using given LIS source file (.tar.gz or lis-next)
# Usage: ./customLISInstall.sh -CustomLIS lisnext or tar file link -LISbranch a specific branch or default is master
#
#######################################################################

#HOW TO PARSE THE ARGUMENTS.. SOURCE - http://stackoverflow.com/questions/4882349/parsing-shell-script-arguments

while echo $1 | grep ^- > /dev/null; do
    eval $( echo $1 | sed 's/-//g' | tr -d '\012')=$2
    shift
    shift
done
#
# Constants/Globals
#
ICA_TESTRUNNING="TestRunning"      # The test is running
ICA_TESTCOMPLETED="TestCompleted"  # The test completed successfully
ICA_TESTABORTED="TestAborted"      # Error during the setup of the test
ICA_TESTFAILED="TestFailed"        # Error occurred during the test

#######################################################################
#
# LogMsg()
#
#######################################################################
LogMsg()
{
    echo `date "+%b %d %Y %T"` : "${1}"    # Add the time stamp to the log message
    echo "${1}" >> ~/build-CustomLIS.txt
}

UpdateTestState()
{
    echo "${1}" > ~/state.txt
}

if [ -z "$CustomLIS" ]; then
	echo "Please mention -CustomLIS next"
	exit 1
fi
if [ -z "$LISbranch" ]; then
	echo "Not mentioned LIS branch, Use Master branch"
	LISbranch="master"
fi
touch ~/build-CustomLIS.txt

#Detect Distro and it's version
DistroName="Unknown"
DistroVersion="Unknown"
if [ -f /etc/redhat-release ] ; then
	DistroName='REDHAT'
	DistroVersion=`cat /etc/redhat-release | sed s/.*release\ // | sed s/\ .*//`
elif [ -f /etc/centos-release ] ; then
	DistroName==`cat /etc/centos-release | sed s/^\ // |sed s/\ .*//`
	DistroName='CENTOS'
	DistroVersion=`cat /etc/centos-release | sed s/.*release\ // | sed s/\ .*//`
elif [ -f /etc/SuSE-release ] ; then
	DistroName=`cat /etc/SuSE-release | tr "\n" ' '| sed s/VERSION.*//`
	DistroVersion=`cat /etc/SuSE-release | tr "\n" ' ' | sed s/.*=\ //`
elif [ -f /etc/debian_version ] ; then
	DistroName="Debian `cat /etc/debian_version`"
	DistroVersion=""
fi
if [ -f /etc/UnitedLinux-release ] ; then
	DistroName="${DistroName}[`cat /etc/UnitedLinux-release | tr "\n" ' ' | sed s/VERSION.*//`]"
fi
LogMsg "*****OS Info*****"
cat /etc/*-release >> ~/build-CustomLIS.txt 2>&1
LogMsg "*****Kernen Info*****"
uname -r >> ~/build-CustomLIS.txt 2>&1
LogMsg "*****LIS Info*****"
modinfo hv_vmbus >> ~/build-CustomLIS.txt 2>&1
kernel=`uname -r`
if [ "${CustomLIS}" == "lisnext" ]; then
	LISSource="https://github.com/LIS/lis-next.git"
	sourceDir="lis-next"
elif [ "${CustomLIS}" == "netnext" ]; then
	LISSource="https://git.kernel.org/pub/scm/linux/kernel/git/davem/net-next.git"
	sourceDir="net-next"
elif [[ $CustomLIS == *.rpm ]]; then
	LogMsg "Custom LIS:$CustomLIS"
	sed -i '/^exclude/c\#exclude' /etc/yum.conf
	yum install -y wget tar
	LogMsg "Debian package web link detected. Downloading $CustomLIS"
	wget $CustomLIS
	LogMsg "Installing ${CustomLIS##*/}"
	rpm -ivh "${CustomLIS##*/}"  >> ~/build-CustomLIS.txt 2>&1
	LISInstallStatus=$?
	UpdateTestState $ICA_TESTCOMPLETED
	if [ $LISInstallStatus -ne 0 ]; then
		LogMsg "CUSTOM_LIS_FAIL"
		UpdateTestState $ICA_TESTFAILED
	else
		LogMsg "CUSTOM_LIS_SUCCESS"
		UpdateTestState $ICA_TESTCOMPLETED
	fi
	exit 0
elif [[ $CustomLIS == *.tar.gz ]]; then
	LogMsg "Custom LIS:$CustomLIS"
	sed -i '/^exclude/c\#exclude' /etc/yum.conf
	yum install -y git make tar gcc bc patch dos2unix wget xz >> ~/build-CustomLIS.txt 2>&1
	LogMsg "LIS tar file web link detected. Downloading $CustomLIS"
	wget $CustomLIS
	LogMsg "Extracting ${CustomLIS##*/}"
	tar -xvzf "${CustomLIS##*/}"
	LogMsg "Installing ${CustomLIS##*/}"
	cd LISISO
	./install.sh  >> ~/build-CustomLIS.txt 2>&1
	LISInstallStatus=$?
	UpdateTestState $ICA_TESTCOMPLETED
	modinfo hv_vmbus >> ~/build-CustomLIS.txt 2>&1
	if [ $LISInstallStatus -ne 0 ]; then
		LogMsg "CUSTOM_LIS_FAIL"
		UpdateTestState $ICA_TESTFAILED
	else
		LogMsg "CUSTOM_LIS_SUCCESS"
		UpdateTestState $ICA_TESTCOMPLETED
	fi
	exit 0
fi
LogMsg "Custom LIS:$CustomLIS"

if [ $DistroName == "SLES" -o $DistroName == "SUSE" ]; then
	zypper --non-interactive install git-core make tar gcc bc patch dos2unix wget xz 
	LogMsg "LIS doesn't support for $DistroName distro..."
elif [ $DistroName == "CENTOS" -o $DistroName == "REDHAT" -o $DistroName == "FEDORA" -o $DistroName == "ORACLELINUX" ]; then
	LogMsg "Installing packages git make tar gcc bc patch dos2unix wget ..."
	sed -i '/^exclude/c\#exclude' /etc/yum.conf
	yum install -y git make tar gcc bc patch dos2unix wget xz >> ~/build-CustomLIS.txt 2>&1
	LogMsg "Downloading LIS source from ${LISSource}..."
	git clone ${LISSource} >> ~/build-CustomLIS.txt 2>&1
	cd ${sourceDir}
	git checkout ${LISbranch}
	LogMsg "Downloaded LIS from this ${LISbranch} branch..."
	if [[ $DistroVersion == *"5."* ]]; then
		LISsourceDir=hv-rhel5.x/hv
	elif [[ $DistroVersion == *"6."* ]]; then
		LISsourceDir=hv-rhel6.x/hv
	elif [[ $DistroVersion == *"7."* ]]; then
		LISsourceDir=hv-rhel7.x/hv
	fi
	cd $LISsourceDir
	LISDir=`pwd`
	LogMsg "Installing kernel-devel-${kernel} for LIS..."
	# TODO - code refactoring should fix non Microsoft blob access
	yum install -y "https://partnerpipelineshare.blob.core.windows.net/kernel-devel-rpms/kernel-devel-${kernel}.rpm" ~/build-CustomLIS.txt 2>&1
	LogMsg "LIS is installing from this ${LISDir} branch..."
	./*-hv-driver-install >> ~/build-CustomLIS.txt 2>&1
	if [ $? -ne 0 ]; then
		LogMsg "CUSTOM_LIS_FAIL"
		UpdateTestState $ICA_TESTFAILED
		exit 0
	fi
elif [ $DistroName == "UBUNTU" ]; then
	LogMsg "LIS doesn't support for $DistroName distro..."
fi
UpdateTestState $ICA_TESTCOMPLETED
sleep 10
LogMsg "CUSTOM_LIS_SUCCESS"
sleep 10
exit 0
