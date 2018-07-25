#!/bin/bash

#######################################################################
#
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
#######################################################################

#######################################################################
#
#
#
# Description:
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

if [ -z "$CustomKernel" ]; then
        echo "Please mention -CustomKernel next"
        exit 1
fi
if [ -z "$logFolder" ]; then
        logFolder="~"
        echo "-logFolder is not mentioned. Using ~"
else
        echo "Using Log Folder $logFolder"
fi

LogMsg()
{
    echo `date "+%b %d %Y %T"` : "${1}"    # Add the time stamp to the log message
    echo "${1}" >> $logFolder/build-CustomKernel.txt
}

UpdateTestState()
{
    echo "${1}" > $logFolder/state.txt
}

touch $logFolder/build-CustomKernel.txt

CheckInstallLockUbuntu()
{
        dpkgPID=$(pidof dpkg)
        if [ $? -eq 0 ];then
                LogMsg "Another install is in progress. Waiting 10 seconds."
                sleep 10
                CheckInstallLockUbuntu
        else
                LogMsg "No lock on dpkg present."
        fi
}

InstallKernel()
{
        sleep 10
        if [ "${CustomKernel}" == "linuxnext" ]; then
                kernelSource="https://git.kernel.org/pub/scm/linux/kernel/git/next/linux-next.git"
                sourceDir="linux-next"
        elif [ "${CustomKernel}" == "proposed" ]; then
                DISTRO=`grep -ihs "buntu\|Suse\|Fedora\|Debian\|CentOS\|Red Hat Enterprise Linux" /etc/{issue,*release,*version}`
                if [[ $DISTRO =~ "Xenial" ]];
                then
                        LogMsg "Enabling proposed repositry..."
                        echo "deb http://archive.ubuntu.com/ubuntu/ xenial-proposed restricted main multiverse universe" >> /etc/apt/sources.list
                        rm -rf /etc/apt/preferences.d/proposed-updates
                        LogMsg "Installing linux-image-generic from proposed repository."
                        apt -y update >> $logFolder/build-CustomKernel.txt 2>&1
                        apt -y --fix-missing upgrade >> $logFolder/build-CustomKernel.txt 2>&1
                        kernelInstallStatus=$?
                elif [[ $DISTRO =~ "Trusty" ]];
                then
                        LogMsg "Enabling proposed repositry..."
                        echo "deb http://archive.ubuntu.com/ubuntu/ trusty-proposed restricted main multiverse universe" >> /etc/apt/sources.list
                        rm -rf /etc/apt/preferences.d/proposed-updates
                        LogMsg "Installing linux-image-generic from proposed repository."
                        apt -y update >> $logFolder/build-CustomKernel.txt 2>&1
                        apt -y --fix-missing upgrade >> $logFolder/build-CustomKernel.txt 2>&1
                        kernelInstallStatus=$?
                fi
                UpdateTestState $ICA_TESTCOMPLETED
                if [ $kernelInstallStatus -ne 0 ]; then
                        LogMsg "CUSTOM_KERNEL_FAIL"
                        UpdateTestState $ICA_TESTFAILED
                else
                        LogMsg "CUSTOM_KERNEL_SUCCESS"
                        UpdateTestState $ICA_TESTCOMPLETED
                fi
        elif [ "${CustomKernel}" == "proposed" ]; then
                DISTRO=`grep -ihs "buntu\|Suse\|Fedora\|Debian\|CentOS\|Red Hat Enterprise Linux" /etc/{issue,*release,*version}`
                if [[ $DISTRO =~ "Xenial" ]];
                then
                        LogMsg "Enabling proposed repositry..."
                        echo "deb http://archive.ubuntu.com/ubuntu/ xenial-proposed restricted main multiverse universe" >> /etc/apt/sources.list
                        rm -rf /etc/apt/preferences.d/proposed-updates
                        LogMsg "Installing linux-image-generic from proposed repository."
                        apt -y update >> $logFolder/build-CustomKernel.txt 2>&1
                        apt -y --fix-missing upgrade >> $logFolder/build-CustomKernel.txt 2>&1
                        kernelInstallStatus=$?
                elif [[ $DISTRO =~ "Trusty" ]];
                then
                        LogMsg "Enabling proposed repositry..."
                        echo "deb http://archive.ubuntu.com/ubuntu/ trusty-proposed restricted main multiverse universe" >> /etc/apt/sources.list
                        rm -rf /etc/apt/preferences.d/proposed-updates
                        LogMsg "Installing linux-image-generic from proposed repository."
                        apt -y update >> $logFolder/build-CustomKernel.txt 2>&1
                        apt -y --fix-missing upgrade >> $logFolder/build-CustomKernel.txt 2>&1
                        kernelInstallStatus=$?
                fi
                UpdateTestState $ICA_TESTCOMPLETED
                if [ $kernelInstallStatus -ne 0 ]; then
                        LogMsg "CUSTOM_KERNEL_FAIL"
                        UpdateTestState $ICA_TESTFAILED
                else
                        LogMsg "CUSTOM_KERNEL_SUCCESS"
                        UpdateTestState $ICA_TESTCOMPLETED
                fi
        elif [ "${CustomKernel}" == "ppa" ]; then
                DISTRO=`grep -ihs "buntu\|Suse\|Fedora\|Debian\|CentOS\|Red Hat Enterprise Linux" /etc/{issue,*release,*version}`
                if [[ $DISTRO =~ "Ubuntu" ]];
                then
                        LogMsg "Enabling ppa repositry..."
                        DEBIAN_FRONTEND=noninteractive add-apt-repository --yes ppa:canonical-kernel-team/ppa
                        apt -y update >> $logFolder/build-CustomKernel.txt 2>&1
                        LogMsg "Installing linux-image-generic from proposed repository."
                        apt -y --fix-missing upgrade >> $logFolder/build-CustomKernel.txt 2>&1
                        kernelInstallStatus=$?
                fi
                UpdateTestState $ICA_TESTCOMPLETED
                if [ $kernelInstallStatus -ne 0 ]; then
                        LogMsg "CUSTOM_KERNEL_FAIL"
                        UpdateTestState $ICA_TESTFAILED
                else
                        LogMsg "CUSTOM_KERNEL_SUCCESS"
                        UpdateTestState $ICA_TESTCOMPLETED
                fi
        elif [ "${CustomKernel}" == "latest" ]; then
                DISTRO=`grep -ihs "buntu\|Suse\|Fedora\|Debian\|CentOS\|Red Hat Enterprise Linux" /etc/{issue,*release,*version}`
                if [[ $DISTRO =~ "Ubuntu" ]];
                then
                        LogMsg "Installing linux-image-generic from repository."
                        apt -y update >> $logFolder/build-CustomKernel.txt 2>&1
                        apt -y --fix-missing upgrade >> $logFolder/build-CustomKernel.txt 2>&1
                        LogMsg "Installing linux-image-generic from proposed repository."
                        apt -y update >> $logFolder/build-CustomKernel.txt 2>&1
                        apt -y --fix-missing upgrade >> $logFolder/build-CustomKernel.txt 2>&1
                        kernelInstallStatus=$?
                fi
                UpdateTestState $ICA_TESTCOMPLETED
                if [ $kernelInstallStatus -ne 0 ]; then
                        LogMsg "CUSTOM_KERNEL_FAIL"
                        UpdateTestState $ICA_TESTFAILED
                else
                        LogMsg "CUSTOM_KERNEL_SUCCESS"
                        UpdateTestState $ICA_TESTCOMPLETED
                fi
        elif [ "${CustomKernel}" == "netnext" ]; then
                kernelSource="https://git.kernel.org/pub/scm/linux/kernel/git/davem/net-next.git"
                sourceDir="net-next"
        elif [[ $CustomKernel == *.deb ]]; then
                LogMsg "Custom Kernel:$CustomKernel"
                apt-get update
                if [[ $CustomKernel =~ "http" ]];then
                        CheckInstallLockUbuntu
                        apt-get install wget
                        LogMsg "Debian package web link detected. Downloading $CustomKernel"
                        wget $CustomKernel
                        LogMsg "Installing ${CustomKernel##*/}"
                        dpkg -i "${CustomKernel##*/}"  >> $logFolder/build-CustomKernel.txt 2>&1
                        kernelInstallStatus=$?
                else
                        CheckInstallLockUbuntu
                        prefix="localfile:"
                        LogMsg "Installing ${CustomKernel#$prefix}"
                        dpkg -i "${CustomKernel#$prefix}"  >> $logFolder/build-CustomKernel.txt 2>&1
                        kernelInstallStatus=$?
                fi

                UpdateTestState $ICA_TESTCOMPLETED
                if [ $kernelInstallStatus -ne 0 ]; then
                        LogMsg "CUSTOM_KERNEL_FAIL"
                        UpdateTestState $ICA_TESTFAILED
                else
                        LogMsg "CUSTOM_KERNEL_SUCCESS"
                        DEBIAN_FRONTEND=noninteractive apt-get -y remove linux-image-$(uname -r)
                        UpdateTestState $ICA_TESTCOMPLETED
                fi
        elif [[ $CustomKernel == *.rpm ]]; then
                LogMsg "Custom Kernel:$CustomKernel"

                if [[ $CustomKernel =~ "http" ]];then
                        yum -y install wget
                        LogMsg "RPM package web link detected. Downloading $CustomKernel"
                        wget $CustomKernel
                        LogMsg "Installing ${CustomKernel##*/}"
                        rpm -ivh "${CustomKernel##*/}"  >> $logFolder/build-CustomKernel.txt 2>&1
                        kernelInstallStatus=$?

                else
                        prefix="localfile:"
                        LogMsg "Installing ${CustomKernel#$prefix}"
                        rpm -ivh "${CustomKernel#$prefix}"  >> $logFolder/build-CustomKernel.txt 2>&1
                        kernelInstallStatus=$?

                fi
                UpdateTestState $ICA_TESTCOMPLETED
                if [ $kernelInstallStatus -ne 0 ]; then
                        LogMsg "CUSTOM_KERNEL_FAIL"
                        UpdateTestState $ICA_TESTFAILED
                else
                        LogMsg "CUSTOM_KERNEL_SUCCESS"
                        UpdateTestState $ICA_TESTCOMPLETED
                        rpm -e kernel-$(uname -r)
                        grub2-set-default 0
                fi
        fi
        if [[ ${CustomKernel} == "linuxnext" ]] || [[ ${CustomKernel} == "netnext" ]]; then
                LogMsg "Custom Kernel:$CustomKernel"
                chmod +x $logFolder/DetectLinuxDistro.sh
                LinuxDistro=`$logFolder/DetectLinuxDistro.sh`
                if [ $LinuxDistro == "SLES" -o $LinuxDistro == "SUSE" ]; then
                        #zypper update
                        zypper --non-interactive install git-core make tar gcc bc patch dos2unix wget xz
                        #TBD
                elif [ $LinuxDistro == "CENTOS" -o $LinuxDistro == "REDHAT" -o $LinuxDistro == "FEDORA" -o $LinuxDistro == "ORACLELINUX" ]; then
                        #yum update
                        yum install -y git make tar gcc bc patch dos2unix wget xz
                        #TBD
                elif [ $LinuxDistro == "UBUNTU" ]; then
                        unset UCF_FORCE_CONFFOLD
                        export UCF_FORCE_CONFFNEW=YES
                        export DEBIAN_FRONTEND=noninteractive
                        ucf --purge /etc/kernel-img.conf
                        export DEBIAN_FRONTEND=noninteractive
                        LogMsg "Updating distro..."
                        CheckInstallLockUbuntu
                        apt-get update
                        LogMsg "Installing packages git make tar gcc bc patch dos2unix wget ..."
                        apt-get install -y git make tar gcc bc patch dos2unix wget >> $logFolder/build-CustomKernel.txt 2>&1
                        LogMsg "Installing kernel-package ..."
                        apt-get -o Dpkg::Options::="--force-confnew" -y install kernel-package >> $logFolder/build-CustomKernel.txt 2>&1
                        rm -rf linux-next
                        LogMsg "Downloading kernel source..."
                        git clone ${kernelSource} >> $logFolder/build-CustomKernel.txt 2>&1
                        cd ${sourceDir}
                        #Download kernel build shell script...
                        wget https://raw.githubusercontent.com/simonxiaoss/linux_performance_test/master/git_bisect/build-ubuntu.sh
                        chmod +x build-ubuntu.sh
                        #Start installing kernel
                        LogMsg "Building and Installing kernel..."
                        ./build-ubuntu.sh  >> $logFolder/build-CustomKernel.txt 2>&1
                        kernelInstallStatus=$?
                        if [ $kernelInstallStatus -eq 0 ]; then
                                LogMsg "CUSTOM_KERNEL_SUCCESS"
                                UpdateTestState $ICA_TESTFAILED
                        else
                                LogMsg "CUSTOM_KERNEL_FAIL"
                                UpdateTestState $ICA_TESTFAILED
                        fi
                fi
        fi
        UpdateTestState $ICA_TESTCOMPLETED
        return $kernelInstallStatus
}
InstallKernel
exit 0
