#!/bin/bash

#######################################################################
#
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
# 
#######################################################################

#######################################################################
#
# perf_lagscope.sh
# Description:
#    Download and run lagscope latency tests.
#    This script needs to be run on client VM.
#
# Supported Distros:
#    Ubuntu 16.04
#######################################################################

CONSTANTS_FILE="./constants.sh"
ICA_TESTRUNNING="TestRunning"		# The test is running
ICA_TESTCOMPLETED="TestCompleted"	# The test completed successfully
ICA_TESTABORTED="TestAborted"		# Error during the setup of the test
ICA_TESTFAILED="TestFailed"			# Error occurred during the test
touch ./lagscopeTest.log


InstallLAGSCOPE() {
		DISTRO=`grep -ihs "buntu\|Suse\|Fedora\|Debian\|CentOS\|Red Hat Enterprise Linux\|clear-linux-os" /etc/{issue,*release,*version} /usr/lib/os-release`

		if [[ $DISTRO =~ "Ubuntu" ]];
		then
			LogMsg "Detected UBUNTU"
				LogMsg "Configuring ${1} for lagscope test..."
				ssh ${1} "until dpkg --force-all --configure -a; sleep 10; do echo 'Trying again...'; done"
				ssh ${1} "apt-get update"
				ssh ${1} "apt-get -y install libaio1 sysstat git bc make gcc"
				ssh ${1} "rm -rf lagscope"
				ssh ${1} "git clone https://github.com/Microsoft/lagscope"
				ssh ${1} "cd lagscope/src && make && make install"
				
		elif [[ $DISTRO =~ "Red Hat Enterprise Linux Server release 6" ]];
		then
				LogMsg "Detected Redhat 6.x"
				ssh ${1} "rpm -ivh https://dl.fedoraproject.org/pub/epel/epel-release-latest-6.noarch.rpm"
				ssh ${1} "yum -y --nogpgcheck install libaio1 sysstat git bc make gcc"
				ssh ${1} "yum -y --nogpgcheck install gcc-c++"

				ssh ${1} "wget http://ftp.heanet.ie/mirrors/gnu/libc/glibc-2.14.1.tar.gz"
				ssh ${1} "tar xvf glibc-2.14.1.tar.gz"
				ssh ${1} "mv glibc-2.14.1 glibc-2.14 && cd glibc-2.14 && mkdir build && cd build && ../configure --prefix=/opt/glibc-2.14 && make && make install && export LD_LIBRARY_PATH=/opt/glibc-2.14/lib:$LD_LIBRARY_PATH"
				
				ssh ${1} "rm -rf lagscope"
				ssh ${1} "git clone https://github.com/Microsoft/lagscope"
				ssh ${1} "cd lagscope/src && make && make install"
				ssh ${1} "iptables -F"

		elif [[ $DISTRO =~ "Red Hat Enterprise Linux Server release 7" ]];
		then
				LogMsg "Detected Redhat 7.x"
				ssh ${1} "rpm -ivh https://dl.fedoraproject.org/pub/epel/epel-release-latest-7.noarch.rpm"
				ssh ${1} "yum -y --nogpgcheck install libaio1 sysstat git bc make gcc"
				ssh ${1} "rm -rf lagscope"
				ssh ${1} "git clone https://github.com/Microsoft/lagscope"
				ssh ${1} "cd lagscope/src && make && make install"
				ssh ${1} "iptables -F"
				
		elif [[ $DISTRO =~ "CentOS Linux release 6" ]];
		then
				LogMsg "Detected CentOS 6.x"
				ssh ${1} "rpm -ivh https://dl.fedoraproject.org/pub/epel/epel-release-latest-6.noarch.rpm"
				ssh ${1} "yum -y --nogpgcheck install libaio1 sysstat git bc make gcc"
				ssh ${1} "yum -y --nogpgcheck install gcc-c++"
				ssh ${1} "rm -rf lagscope"
				ssh ${1} "git clone https://github.com/Microsoft/lagscope"
				ssh ${1} "cd lagscope/src && make && make install"
				ssh ${1} "iptables -F"
				
		elif [[ $DISTRO =~ "CentOS Linux release 7" ]];
		then
				LogMsg "Detected CentOS 7.x"
				ssh ${1} "rpm -ivh https://dl.fedoraproject.org/pub/epel/epel-release-latest-7.noarch.rpm"
				ssh ${1} "yum -y --nogpgcheck install libaio1 sysstat git bc make gcc"
				ssh ${1} "rm -rf lagscope"
				ssh ${1} "git clone https://github.com/Microsoft/lagscope"
				ssh ${1} "cd lagscope/src && make && make install"
				ssh ${1} "iptables -F"

		elif [[ $DISTRO =~ "SUSE Linux Enterprise Server 12" ]];
		then
		LogMsg "Detected SLES12"
				ssh ${1} "zypper --no-gpg-checks --non-interactive --gpg-auto-import-keys remove gettext-runtime-mini*"
				ssh ${1} "zypper --no-gpg-checks --non-interactive --gpg-auto-import-keys install sysstat git bc make gcc grub2"
				ssh ${1} "rm -rf lagscope"
				ssh ${1} "git clone https://github.com/Microsoft/lagscope"
				ssh ${1} "cd lagscope/src && make && make install"
				ssh ${1} "iptables -F"
		elif [[ $DISTRO =~ "clear-linux-os" ]];
		then
				LogMsg "Detected Clear Linux OS. Installing required packages"
				ssh ${1} "swupd bundle-add dev-utils-dev sysadmin-basic performance-tools os-testsuite-phoronix network-basic openssh-server dev-utils os-core os-core-dev"
				ssh ${1} "iptables -F"
				
		else
				LogMsg "Unknown Distro"
				UpdateTestState "TestAborted"
				UpdateSummary "Unknown Distro, test aborted"
				return 1
	fi
}
LogMsg()
{
    echo `date "+%b %d %Y %T"` : "${1}"    # Add the time stamp to the log message
    echo "${1}" >> ./ntttcpTest.log
}

UpdateTestState()
{
    echo "${1}" > ./state.txt
}

if [ -e ${CONSTANTS_FILE} ]; then
    source ${CONSTANTS_FILE}
else
    errMsg="Error: missing ${CONSTANTS_FILE} file"
    LogMsg "${errMsg}"
    UpdateTestState $ICA_TESTABORTED
    exit 10
fi

if [ ! ${server} ]; then
	errMsg="Please add/provide value for server in constants.sh. server=<server ip>"
	LogMsg "${errMsg}"
	echo "${errMsg}" >> ./summary.log
	UpdateTestState $ICA_TESTABORTED
	exit 1
fi
if [ ! ${client} ]; then
	errMsg="Please add/provide value for client in constants.sh. client=<client ip>"
	LogMsg "${errMsg}"
	echo "${errMsg}" >> ./summary.log
	UpdateTestState $ICA_TESTABORTED
	exit 1
fi

if [ ! ${pingIteration} ]; then
	errMsg="Please add/provide value for pingIteration in constants.sh. pingIteration=1000000"
	LogMsg "${errMsg}"
	echo "${errMsg}" >> ./summary.log
	UpdateTestState $ICA_TESTABORTED
	exit 1
fi

#Make & build ntttcp on client and server Machine

LogMsg "Configuring client ${client}..."
InstallLAGSCOPE ${client}

LogMsg "Configuring server ${server}..."
InstallLAGSCOPE ${server}

#Now, start the ntttcp client on client VM.

LogMsg "Now running Lagscope test"
LogMsg "Starting server."
ssh root@${server} "lagscope -r -D"
sleep 1
LogMsg "lagscope client running..."
ssh root@${client} "lagscope -s${server} -i0 -n${pingIteration} -H > lagscope-n${pingIteration}-output.txt"
LogMsg "Test finsished."
UpdateTestState ICA_TESTCOMPLETED

