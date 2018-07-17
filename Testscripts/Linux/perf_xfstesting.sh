#!/bin/bash

#######################################################################
#
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
#######################################################################

#######################################################################
#
# perf_xfstesting.sh
# Description:
#       Download and run xfs tests.
#
# Supported Distros:
#       Ubuntu 16.04
# Supported Filesystems : ext4, xfs, btrfs

#######################################################################

while echo $1 | grep ^- > /dev/null; do
    eval $( echo $1 | sed 's/-//g' | tr -d '\012')=$2
    shift
    shift
done

XFSTestConfigFile="xfstests-config.config"
touch /root/XFSTestingConsole.log

LogMsg()
{
        echo `date "+%b %d %Y %T"` : "${1}"     # Add the time stamp to the log message
        echo "${1}" >> /root/XFSTestingConsole.log
}

InstallXFSTestTools()
{
    DISTRO=`grep -ihs "buntu\|Suse\|Fedora\|Debian\|CentOS\|Red Hat Enterprise Linux\|clear-linux-os" /etc/{issue,*release,*version} /usr/lib/os-release`
    if [[ $DISTRO =~ "Ubuntu" ]] || [[ $DISTRO =~ "Debian" ]];
    then
        LogMsg "Detected Ubuntu/Debian. Installing required packages..."
        until dpkg --force-all --configure -a; sleep 10; do echo 'Trying again...'; done
        apt-get update
        apt-get -y install gcc xfslibs-dev uuid-dev libtool xfsprogs e2fsprogs automake libuuid1 libuuidm-ocaml-dev attr libattr1-dev libacl1-dev libaio-dev  gawk xfsprogs libgdbm-dev quota fio dbench bc make dos2unix samba
        git clone git://git.kernel.org/pub/scm/fs/xfs/xfstests-dev.git
        mv xfstests-dev xfstests
        cd xfstests
        ./configure
        make
        cd ..
        LogMsg "Packages installation complete."
    else
        LogMsg "Unknown Distro"
        exit 10
    fi
}

if [ -e ${XFSTestConfigFile} ]; then
	LogMsg "${XFSTestConfigFile} File is present."
else
    errMsg="Error: missing ${XFSTestConfigFile} file"
    LogMsg "${errMsg}"
    exit 10
fi

#Configure XFS Tools
InstallXFSTestTools

dos2unix ${XFSTestConfigFile}
cp -f ${XFSTestConfigFile} ./xfstests/local.config

mkdir -p /root/ext4
mkdir -p /root/xfs
mkdir -p /root/cifs
mkdir -p /root/sdc
mkdir -p /root/btrfs
#RunTests
if [[ $TestFileSystem == "cifs" ]];
then
    cd xfstests
    #Download Exclusion files
    wget https://wiki.samba.org/images/d/db/Xfstests.exclude.very-slow.txt -O tests/cifs/exclude.very-slow
    wget https://wiki.samba.org/images/b/b0/Xfstests.exclude.incompatible-smb3.txt -O tests/cifs/exclude.incompatible-smb3
    mkfs.xfs -f /dev/sdc
    mount -o nobarrier /dev/sdc /root/sdc
    pass='abcdefghijklmnopqrstuvwxyz'
    (echo "$pass"; echo "$pass") | smbpasswd -s -a root
    echo '[share]' >> /etc/samba/smb.conf
    echo 'path = /root/sdc' >> /etc/samba/smb.conf
    echo 'valid users = root' >> /etc/samba/smb.conf
    echo 'read only = no' >> /etc/samba/smb.conf
    ./check -s $TestFileSystem -E tests/cifs/exclude.incompatible-smb3 >> /root/XFSTestingConsole.log
    cd ..
elif [[ $TestFileSystem == "ext4" ]] || [[ $TestFileSystem == "xfs" ]] || [[ $TestFileSystem == "btrfs" ]];
then
    LogMsg "Formatting /dev/sdc with ${TestFileSystem}"
    if [[ $TestFileSystem == "xfs" ]] || [[ $TestFileSystem == "btrfs" ]];
    then
        mkfs.$TestFileSystem -f /dev/sdc
    else
        echo y | mkfs -t $TestFileSystem /dev/sdc
    fi
    mkdir -p /test2
    cd xfstests
    LogMsg "Runnint tests for $TestFileSystem file system"
    ./check -s $TestFileSystem >> /root/XFSTestingConsole.log
    cd ..
else
    LogMsg "$TestFileSystem is not supported."
fi
LogMsg "TestCompleted"
