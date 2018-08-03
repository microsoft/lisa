#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
#
# Sample script to run sysbench.
# In this script, we want to bench-mark device IO performance on a mounted folder.
# You can adapt this script to other situations easily like for stripe disks as RAID0.
# The only thing to keep in mind is that each different configuration you're testing
# must log its output to a different directory.
#

HOMEDIR="/root"
LogMsg()
{
    echo "[$(date +"%x %r %Z")] ${1}"
	echo "[$(date +"%x %r %Z")] ${1}" >> "${HOMEDIR}/runlog.txt"
}
LogMsg "Sleeping 10 seconds.."
sleep 10

#export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/share/oem/bin:/usr/share/oem/python/bin:/opt/bin
CONSTANTS_FILE="$HOMEDIR/constants.sh"
ICA_TESTRUNNING="TestRunning"      # The test is running
ICA_TESTCOMPLETED="TestCompleted"  # The test completed successfully
ICA_TESTABORTED="TestAborted"      # Error during the setup of the test
ICA_TESTFAILED="TestFailed"        # Error occurred during the test
touch ./fioTest.log

if [ -e ${CONSTANTS_FILE} ]; then
    . ${CONSTANTS_FILE}
else
    errMsg="Error: missing ${CONSTANTS_FILE} file"
    LogMsg "${errMsg}"
    UpdateTestState $ICA_TESTABORTED
    exit 10
fi


UpdateTestState()
{
    echo "${1}" > $HOMEDIR/state.txt
}

InstallFIO() 
{
	DISTRO=`grep -ihs "ubuntu\|Suse\|Fedora\|Debian\|CentOS\|Red Hat Enterprise Linux\|clear-linux-os" /etc/{issue,*release,*version} /usr/lib/os-release`

	if [[ $DISTRO =~ "Ubuntu" ]] || [[ $DISTRO =~ "Debian" ]];
	then
		LogMsg "Detected UBUNTU/Debian. Installing required packages"
		until dpkg --force-all --configure -a; sleep 10; do echo 'Trying again...'; done
		apt-get update 
		apt-get install -y pciutils gawk mdadm wget sysstat blktrace bc fio
		if [ $? -ne 0 ]; then
			LogMsg "Error: Unable to install fio"
			exit 1
		fi
		mount -t debugfs none /sys/kernel/debug						
	elif [[ $DISTRO =~ "Red Hat Enterprise Linux Server release 6" ]];
	then
		LogMsg "Detected RHEL 6.x; Installing required packages"
		rpm -ivh https://dl.fedoraproject.org/pub/epel/epel-release-latest-6.noarch.rpm
		yum -y --nogpgcheck install wget sysstat mdadm blktrace libaio fio
		mount -t debugfs none /sys/kernel/debug
	elif [[ $DISTRO =~ "Red Hat Enterprise Linux Server release 7" ]];
	then
		LogMsg "Detected RHEL 7.x; Installing required packages"
		rpm -ivh https://dl.fedoraproject.org/pub/epel/epel-release-latest-7.noarch.rpm
		yum -y --nogpgcheck install wget sysstat mdadm blktrace libaio fio
		mount -t debugfs none /sys/kernel/debug	
	elif [[ $DISTRO =~ "CentOS Linux release 6" ]] || [[ $DISTRO =~ "CentOS release 6" ]];
	then
		LogMsg "Detected CentOS 6.x; Installing required packages"
		rpm -ivh https://dl.fedoraproject.org/pub/epel/epel-release-latest-6.noarch.rpm
		yum -y --nogpgcheck install wget sysstat mdadm blktrace libaio fio
		mount -t debugfs none /sys/kernel/debug		
	elif [[ $DISTRO =~ "CentOS Linux release 7" ]];
	then
		LogMsg "Detected CentOS 7.x; Installing required packages"
		rpm -ivh https://dl.fedoraproject.org/pub/epel/epel-release-latest-7.noarch.rpm
		yum -y --nogpgcheck install wget sysstat mdadm blktrace libaio fio
		mount -t debugfs none /sys/kernel/debug
	elif [[ $DISTRO =~ "SUSE Linux Enterprise Server" ]];
	then
		LogMsg "Detected SLES. Installing required packages"
		if [[ $DISTRO =~ "SUSE Linux Enterprise Server 12" ]];
		then
			LogMsg "Detected SLES 12"
			repositoryUrl="https://download.opensuse.org/repositories/benchmark/SLE_12_SP3_Backports/benchmark.repo"
		elif [[ $DISTRO =~ "SUSE Linux Enterprise Server 15" ]];
		then
			LogMsg "Detected SLES 15"
			repositoryUrl="https://download.opensuse.org/repositories/network:utilities/SLE_15/network:utilities.repo"
		else
			LogMsg "Error: Unknown SLES version"
			UpdateTestState "TestAborted"
			exit 1			
		fi
		zypper addrepo $repositoryUrl
		zypper --no-gpg-checks --non-interactive --gpg-auto-import-keys refresh
		zypper --no-gpg-checks --non-interactive --gpg-auto-import-keys install wget mdadm blktrace libaio1 sysstat
		zypper --no-gpg-checks --non-interactive --gpg-auto-import-keys install fio
		which fio
		if [ $? -ne 0 ]; then
			LogMsg "Info: fio is not available in repository. So, Installing fio using rpm"
			fioUrl="https://eosgpackages.blob.core.windows.net/testpackages/tools/fio-sles-x86_64.rpm"
			wget --no-check-certificate $fioUrl
			LogMsg "zypper --no-gpg-checks --non-interactive --gpg-auto-import-keys install ${fioUrl##*/}"
			zypper --no-gpg-checks --non-interactive --gpg-auto-import-keys install ${fioUrl##*/}
			which fio
			if [ $? -ne 0 ]; then
				LogMsg "Error: Unable to install fio from source/rpm"
				UpdateTestState "TestAborted"
				exit 1
			fi
		else
			LogMsg "Info: fio installed from repository"
		fi
	elif [[ $DISTRO =~ "clear-linux-os" ]];
	then
		LogMsg "Detected Clear Linux OS. Installing required packages"
		swupd bundle-add dev-utils-dev sysadmin-basic performance-tools os-testsuite-phoronix network-basic openssh-server dev-utils os-core os-core-dev
	else
		LogMsg "Unknown Distro"
		UpdateTestState "TestAborted"
		UpdateSummary "Unknown Distro, test aborted"
		exit 1
	fi
}

RunFIO()
{
	UpdateTestState ICA_TESTRUNNING
	FILEIO="--size=${fileSize} --direct=1 --ioengine=libaio --filename=fiodata --overwrite=1  "

	####################################
	#All run config set here
	#

	#Log Config
	
	mkdir $HOMEDIR/FIOLog/jsonLog
	mkdir $HOMEDIR/FIOLog/iostatLog
	mkdir $HOMEDIR/FIOLog/blktraceLog

	#LOGDIR="${HOMEDIR}/FIOLog"
	JSONFILELOG="${LOGDIR}/jsonLog"
	IOSTATLOGDIR="${LOGDIR}/iostatLog"
	BLKTRACELOGDIR="${LOGDIR}/blktraceLog"
	LOGFILE="${LOGDIR}/fio-test.log.txt"	

	#redirect blktrace files directory
	Resource_mount=$(mount -l | grep /sdb1 | awk '{print$3}')
	blk_base="${Resource_mount}/blk-$(date +"%m%d%Y-%H%M%S")"
	mkdir $blk_base
	#
	#
	#Test config
	#
	#

	#All possible values for file-test-mode are randread randwrite read write
	#modes='randread randwrite read write'
	iteration=0
	#startThread=1
	#startIO=8
	#numjobs=1

	#Max run config
	#ioruntime=300
	#maxThread=1024
	#maxIO=8
	io_increment=128

	####################################
	echo "Test log created at: ${LOGFILE}"
	echo "===================================== Starting Run $(date +"%x %r %Z") ================================"
	echo "===================================== Starting Run $(date +"%x %r %Z") script generated 2/9/2015 4:24:44 PM ================================" >> $LOGFILE

	chmod 666 $LOGFILE
	echo "Preparing Files: $FILEIO"
	echo "Preparing Files: $FILEIO" >> $LOGFILE
	LogMsg "Preparing Files: $FILEIO"
	# Remove any old files from prior runs (to be safe), then prepare a set of new files.
	rm fiodata
	echo "--- Kernel Version Information ---" >> $LOGFILE
	uname -a >> $LOGFILE
	cat /proc/version >> $LOGFILE
	cat /etc/*-release >> $LOGFILE
	echo "--- PCI Bus Information ---" >> $LOGFILE
	lspci >> $LOGFILE
	echo "--- Drive Mounting Information ---" >> $LOGFILE
	mount >> $LOGFILE
	echo "--- Disk Usage Before Generating New Files ---" >> $LOGFILE
	df -h >> $LOGFILE
	fio --cpuclock-test >> $LOGFILE
	fio $FILEIO --readwrite=read --bs=1M --runtime=1 --iodepth=128 --numjobs=8 --name=prepare
	echo "--- Disk Usage After Generating New Files ---" >> $LOGFILE
	df -h >> $LOGFILE
	echo "=== End Preparation  $(date +"%x %r %Z") ===" >> $LOGFILE
	LogMsg "Preparing Files: $FILEIO: Finished."
	####################################
	#Trigger run from here
	for testmode in $modes; do
		io=$startIO
		while [ $io -le $maxIO ]
		do
			Thread=$startThread			
			while [ $Thread -le $maxThread ]
			do
				if [ $Thread -ge 8 ]
				then
					numjobs=8
				else
					numjobs=$Thread
				fi
				iostatfilename="${IOSTATLOGDIR}/iostat-fio-${testmode}-${io}K-${Thread}td.txt"
				nohup iostat -x 5 -t -y > $iostatfilename &
				#capture blktrace output during test
				#LogMsg "INFO: start blktrace for 40 sec on device sdd and sdf"				
				#blk_operation="${blk_base}/blktrace-fio-${testmode}-${io}K-${Thread}td/"							
				#mkdir $blk_operation
				#blktrace -w 40 -d /dev/sdf -D $blk_operation &
				#blktrace -w 40 -d /dev/sdm -D $blk_operation &
				echo "-- iteration ${iteration} ----------------------------- ${testmode} test, ${io}K bs, ${Thread} threads, ${numjobs} jobs, 5 minutes ------------------ $(date +"%x %r %Z") ---" >> $LOGFILE
				LogMsg "Running ${testmode} test, ${io}K bs, ${Thread} threads ..."
				jsonfilename="${JSONFILELOG}/fio-result-${testmode}-${io}K-${Thread}td.json"
				fio $FILEIO --readwrite=$testmode --bs=${io}K --runtime=$ioruntime --iodepth=$Thread --numjobs=$numjobs --output-format=json --output=$jsonfilename --name="iteration"${iteration} >> $LOGFILE
				#fio $FILEIO --readwrite=$testmode --bs=${io}K --runtime=$ioruntime --iodepth=$Thread --numjobs=$numjobs --name="iteration"${iteration} --group_reporting >> $LOGFILE
				iostatPID=`ps -ef | awk '/iostat/ && !/awk/ { print $2 }'`
				kill -9 $iostatPID
				Thread=$(( Thread*2 ))		
				iteration=$(( iteration+1 ))
			done
		io=$(( io * io_increment ))
		done
	done
	####################################
	echo "===================================== Completed Run $(date +"%x %r %Z") script generated 2/9/2015 4:24:44 PM ================================" >> $LOGFILE
	rm fiodata

	compressedFileName="${HOMEDIR}/FIOTest-$(date +"%m%d%Y-%H%M%S").tar.gz"
	LogMsg "INFO: Please wait...Compressing all results to ${compressedFileName}..."
	tar -cvzf $compressedFileName $LOGDIR/

	echo "Test logs are located at ${LOGDIR}"
	UpdateTestState ICA_TESTCOMPLETED
}


CreateRAID0()
{	
	disks=$(ls -l /dev | grep sd[c-z]$ | awk '{print $10}')
	#disks=(`fdisk -l | grep 'Disk.*/dev/sd[a-z]' |awk  '{print $2}' | sed s/://| sort| grep -v "/dev/sd[ab]$" `)
	
	LogMsg "INFO: Check and remove RAID first"
	mdvol=$(cat /proc/mdstat | grep "active raid" | awk {'print $1'})
	if [ -n "$mdvol" ]; then
		echo "/dev/${mdvol} already exist...removing first"
		umount /dev/${mdvol}
		mdadm --stop /dev/${mdvol}
		mdadm --remove /dev/${mdvol}
		mdadm --zero-superblock /dev/sd[c-z][1-5]
	fi
	
	LogMsg "INFO: Creating Partitions"
	count=0
	for disk in ${disks}
	do		
		echo "formatting disk /dev/${disk}"
		(echo d; echo n; echo p; echo 1; echo; echo; echo t; echo fd; echo w;) | fdisk /dev/${disk}
		count=$(( $count + 1 ))
		sleep 1
	done
	LogMsg "INFO: Creating RAID of ${count} devices."
	sleep 1
	mdadm --create ${mdVolume} --level 0 --raid-devices ${count} /dev/sd[c-z][1-5]
	sleep 1
	time mkfs -t $1 -F ${mdVolume}
	mkdir ${mountDir}
	sleep 1
	mount -o nobarrier ${mdVolume} ${mountDir}
	if [ $? -ne 0 ]; then
		LogMsg "Error: Unable to create raid"            
		exit 1
	else
		LogMsg "${mdVolume} mounted to ${mountDir} successfully."
	fi
	
	#LogMsg "INFO: adding fstab entry"
	#echo "${mdVolume}	${mountDir}	ext4	defaults	1 1" >> /etc/fstab
}

CreateLVM()
{	
	disks=$(ls -l /dev | grep sd[c-z]$ | awk '{print $10}')
	#disks=(`fdisk -l | grep 'Disk.*/dev/sd[a-z]' |awk  '{print $2}' | sed s/://| sort| grep -v "/dev/sd[ab]$" `)
	
	#LogMsg "INFO: Check and remove LVM first"
	vgExist=$(vgdisplay)
	if [ -n "$vgExist" ]; then
		umount ${mountDir}
		lvremove -A n -f /dev/${vggroup}/lv1
		vgremove ${vggroup} -f
	fi
	
	LogMsg "INFO: Creating Partition"
	count=0
	for disk in ${disks}
	do		
		echo "formatting disk /dev/${disk}"
		(echo d; echo n; echo p; echo 1; echo; echo; echo t; echo fd; echo w;) | fdisk /dev/${disk}
		count=$(( $count + 1 )) 
	done
	
	LogMsg "INFO: Creating LVM with all data disks"
	pvcreate /dev/sd[c-z][1-5]
	vgcreate ${vggroup} /dev/sd[c-z][1-5]
	lvcreate -l 100%FREE -i 12 -I 64 ${vggroup} -n lv1
	time mkfs -t $1 -F /dev/${vggroup}/lv1
	mkdir ${mountDir}
	mount -o nobarrier /dev/${vggroup}/lv1 ${mountDir}
	if [ $? -ne 0 ]; then
            LogMsg "Error: Unable to create LVM "            
            exit 1
        fi
	
	#LogMsg "INFO: adding fstab entry"
	#echo "${mdVolume}	${mountDir}	ext4	defaults	1 1" >> /etc/fstab
}

############################################################
#	Main body
############################################################

HOMEDIR=$HOME
mv $HOMEDIR/FIOLog/ $HOMEDIR/FIOLog-$(date +"%m%d%Y-%H%M%S")/
mkdir $HOMEDIR/FIOLog
LOGDIR="${HOMEDIR}/FIOLog"
DISTRO=`grep -ihs "buntu\|Suse\|Fedora\|Debian\|CentOS\|Red Hat Enterprise Linux" /etc/{issue,*release,*version}`
if [[ $DISTRO =~ "SUSE Linux Enterprise Server 12" ]];
then
	mdVolume="/dev/md/mdauto0"
else
	mdVolume="/dev/md0"
fi
vggroup="vg1"
mountDir="/data"
cd ${HOMEDIR}

InstallFIO

#Creating RAID before triggering test
CreateRAID0 ext4
#CreateLVM ext4

#Run test from here
LogMsg "*********INFO: Starting test execution*********"
cd ${mountDir}
mkdir sampleDIR
RunFIO
LogMsg "*********INFO: Script execution reach END. Completed !!!*********"
