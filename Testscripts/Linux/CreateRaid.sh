#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
DISTRO=`grep -ihs "buntu\|Suse\|Fedora\|Debian\|CentOS\|Red Hat Enterprise Linux" /etc/{issue,*release,*version}`
if [[ $DISTRO =~ "SUSE Linux Enterprise Server 12" ]];
then
    mdVolume="/dev/md/mdauto0"
else
    mdVolume="/dev/md0"
fi
mountDir="/data"
raidFileSystem="ext4"

#Install Required Packages.
DISTRO=`grep -ihs "buntu\|Suse\|Fedora\|Debian\|CentOS\|Red Hat Enterprise Linux\|clear-linux-os" /etc/{issue,*release,*version} /usr/lib/os-release`

if [[ $DISTRO =~ "Ubuntu" ]] || [[ $DISTRO =~ "Debian" ]];
then
    echo "Detected UBUNTU/Debian. Installing required packages"
    until dpkg --force-all --configure -a; sleep 10; do echo 'Trying again...'; done
    apt-get update
    apt-get install -y mdadm
    if [ $? -ne 0 ]; then
        echo "Error: Unable to install mdadm"
        exit 1
    fi

elif [[ $DISTRO =~ "Red Hat Enterprise Linux Server release 6" ]];
then
    echo "Detected RHEL 6.x; Installing required packages"
    rpm -ivh https://dl.fedoraproject.org/pub/epel/epel-release-latest-6.noarch.rpm
    yum -y --nogpgcheck install mdadm

elif [[ $DISTRO =~ "Red Hat Enterprise Linux Server release 7" ]];
then
    echo "Detected RHEL 7.x; Installing required packages"
    rpm -ivh https://dl.fedoraproject.org/pub/epel/epel-release-latest-7.noarch.rpm
    yum -y --nogpgcheck install mdadm
    mount -t debugfs none /sys/kernel/debug

elif [[ $DISTRO =~ "CentOS Linux release 6" ]] || [[ $DISTRO =~ "CentOS release 6" ]];
then
    echo "Detected CentOS 6.x; Installing required packages"
    rpm -ivh https://dl.fedoraproject.org/pub/epel/epel-release-latest-6.noarch.rpm
    yum -y --nogpgcheck install mdadm
    mount -t debugfs none /sys/kernel/debug

elif [[ $DISTRO =~ "CentOS Linux release 7" ]];
then
    echo "Detected CentOS 7.x; Installing required packages"
    rpm -ivh https://dl.fedoraproject.org/pub/epel/epel-release-latest-7.noarch.rpm
    yum -y --nogpgcheck install mdadm

elif [[ $DISTRO =~ "SUSE Linux Enterprise Server 12" ]];
then
    echo "Detected SLES12. Installing required packages"
    zypper addrepo http://download.opensuse.org/repositories/benchmark/SLE_12_SP2_Backports/benchmark.repo
    zypper --no-gpg-checks --non-interactive --gpg-auto-import-keys refresh
    zypper --no-gpg-checks --non-interactive --gpg-auto-import-keys remove gettext-runtime-mini-0.19.2-1.103.x86_64
    zypper --no-gpg-checks --non-interactive --gpg-auto-import-keys install sysstat
    zypper --no-gpg-checks --non-interactive --gpg-auto-import-keys install grub2
    zypper --no-gpg-checks --non-interactive --gpg-auto-import-keys install mdadm
elif [[ $DISTRO =~ "clear-linux-os" ]];
then
    echo "Detected Clear Linux OS. Installing required packages"
    swupd bundle-add dev-utils-dev sysadmin-basic performance-tools os-testsuite-phoronix network-basic openssh-server dev-utils os-core os-core-dev
else
        echo "Unknown Distro"
        exit 1
fi

#Create Raid of All available Data disks
umount /data
disks=$(ls -l /dev | grep sd[c-z]$ | awk '{print $10}')
echo "INFO: Check and remove active RAID first"
mdvol=$(cat /proc/mdstat | grep "active raid" | awk {'print $1'})
if [ -n "$mdvol" ]; then
        echo "/dev/${mdvol} already exist...removing first"
        umount /dev/${mdvol}
        mdadm --stop /dev/${mdvol}
        mdadm --remove /dev/${mdvol}
        mdadm --zero-superblock /dev/sd[c-z][1-5]
fi
echo "INFO: Creating Partitions"
count=0
for disk in ${disks}
do
        echo "formatting disk /dev/${disk}"
        (echo d; echo n; echo p; echo 1; echo; echo; echo t; echo fd; echo w;) | fdisk /dev/${disk}
        count=$(( $count + 1 ))
        sleep 1
done
echo "INFO: Creating RAID of ${count} devices."
sleep 1
mdadm --create ${mdVolume} --level 0 --raid-devices ${count} /dev/sd[c-z][1-5]
sleep 1
time mkfs -t $raidFileSystem -F ${mdVolume}
mkdir ${mountDir}
sleep 1
mount -o nobarrier ${mdVolume} ${mountDir}
if [ $? -ne 0 ]; then
    echo "Error: Unable to create raid"
    exit 1
else
    echo "${mdVolume} mounted to ${mountDir} successfully."
    exit 0
fi
