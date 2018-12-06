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

CONSTANTS_FILE="$HOMEDIR/constants.sh"
UTIL_FILE="$HOMEDIR/utils.sh"
STATE_FILE="$HOMEDIR/state.txt"
ICA_TESTRUNNING="TestRunning"      # The test is running
ICA_TESTCOMPLETED="TestCompleted"  # The test completed successfully
ICA_TESTABORTED="TestAborted"      # Error during the setup of the test
ICA_TESTFAILED="TestFailed"        # Error occurred during the test
touch ./fioTest.log
touch $STATE_FILE

. ${CONSTANTS_FILE} || {
	errMsg="Error: missing ${CONSTANTS_FILE} file"
	LogMsg "${errMsg}"
	UpdateTestState $ICA_TESTABORTED
	exit 10
}
. ${UTIL_FILE} || {
	errMsg="Error: missing ${UTIL_FILE} file"
	LogMsg "${errMsg}"
	UpdateTestState $ICA_TESTABORTED
	exit 10
}

UpdateTestState()
{
	echo "${1}" > $STATE_FILE
}

RunFIO()
{
	UpdateTestState $ICA_TESTRUNNING
	FILEIO="--size=${fileSize} --direct=1 --ioengine=libaio --filename=${mdVolume} --overwrite=1  "

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
	#modes=(randread randwrite read write)
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
	LogMsg "Test log created at: ${LOGFILE}"
	LogMsg "===================================== Starting Run $(date +"%x %r %Z") ================================"
	LogMsg "===================================== Starting Run $(date +"%x %r %Z") script generated 2/9/2015 4:24:44 PM ================================"

	chmod 666 $LOGFILE
	LogMsg "--- Kernel Version Information ---"
	uname -a >> $LOGFILE
	cat /proc/version >> $LOGFILE
	if [ -f /usr/share/clear/version ]; then
		cat /usr/share/clear/version >> $LOGFILE
	elif [ -f /etc/*-release ]; then
		cat /etc/*-release >> $LOGFILE
	fi
	LogMsg "--- PCI Bus Information ---"
	lspci >> $LOGFILE
	df -h >> $LOGFILE
	fio --cpuclock-test >> $LOGFILE
	####################################
	#Trigger run from here
	for testmode in "${modes[@]}"; do
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
				nohup $iostat_cmd -x 5 -t -y > $iostatfilename &
				#capture blktrace output during test
				#LogMsg "INFO: start blktrace for 40 sec on device sdd and sdf"				
				#blk_operation="${blk_base}/blktrace-fio-${testmode}-${io}K-${Thread}td/"							
				#mkdir $blk_operation
				#blktrace -w 40 -d /dev/sdf -D $blk_operation &
				#blktrace -w 40 -d /dev/sdm -D $blk_operation &
				LogMsg "-- iteration ${iteration} ----------------------------- ${testmode} test, ${io}K bs, ${Thread} threads, ${numjobs} jobs, 5 minutes ------------------ $(date +"%x %r %Z") ---"
				LogMsg "Running ${testmode} test, ${io}K bs, ${Thread} threads ..."
				jsonfilename="${JSONFILELOG}/fio-result-${testmode}-${io}K-${Thread}td.json"
				LogMsg "${fio_cmd} $FILEIO --readwrite=${testmode} --bs=${io}K --runtime=${ioruntime} --iodepth=${Thread} --numjobs=${numjobs} --output-format=json --output=${jsonfilename} --name='iteration'${iteration}"
				$fio_cmd $FILEIO --readwrite=$testmode --bs=${io}K --runtime=$ioruntime --iodepth=$Thread --numjobs=$numjobs --output-format=json --output=$jsonfilename --name="iteration"${iteration} >> $LOGFILE
				#fio $FILEIO --readwrite=$testmode --bs=${io}K --runtime=$ioruntime --iodepth=$Thread --numjobs=$numjobs --name="iteration"${iteration} --group_reporting >> $LOGFILE
				iostatPID=`ps -ef | awk '/iostat/ && !/awk/ { print $2 }'`
				kill -9 $iostatPID
				Thread=$(( Thread*2 ))
				iteration=$(( iteration+1 ))
				if [[ $(detect_linux_distribution) == coreos ]]; then
					Kill_Process 127.0.0.1 fio
				fi
			done
		io=$(( io * io_increment ))
		done
	done
	####################################
	LogMsg "===================================== Completed Run $(date +"%x %r %Z") script generated 2/9/2015 4:24:44 PM ================================"

	compressedFileName="${HOMEDIR}/FIOTest-$(date +"%m%d%Y-%H%M%S").tar.gz"
	LogMsg "INFO: Please wait...Compressing all results to ${compressedFileName}..."
	tar -cvzf $compressedFileName $LOGDIR/

	LogMsg "Test logs are located at ${LOGDIR}"
	UpdateTestState ICA_TESTCOMPLETED
}


CreateRAID0()
{	
	disks=$(ls -l /dev | grep sd[c-z]$ | awk '{print $10}')
	#disks=(`fdisk -l | grep 'Disk.*/dev/sd[a-z]' |awk  '{print $2}' | sed s/://| sort| grep -v "/dev/sd[ab]$" `)
	
	LogMsg "INFO: Check and remove RAID first"
	mdvol=$(cat /proc/mdstat | grep "active raid" | awk {'print $1'})
	if [ -n "$mdvol" ]; then
		LogMsg "/dev/${mdvol} already exist...removing first"
		umount /dev/${mdvol}
		mdadm --stop /dev/${mdvol}
		mdadm --remove /dev/${mdvol}
		mdadm --zero-superblock /dev/sd[c-z][1-5]
	fi
	
	LogMsg "INFO: Creating Partitions"
	count=0
	for disk in ${disks}
	do		
		LogMsg "formatting disk /dev/${disk}"
		(echo d; echo n; echo p; echo 1; echo; echo; echo t; echo fd; echo w;) | fdisk /dev/${disk}
		count=$(( $count + 1 ))
		sleep 1
	done
	LogMsg "INFO: Creating RAID of ${count} devices."
	sleep 1
	mdadm --create ${mdVolume} --level 0 --raid-devices ${count} /dev/sd[c-z][1-5]
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
}

############################################################
#	Main body
############################################################

HOMEDIR=$HOME
mv $HOMEDIR/FIOLog/ $HOMEDIR/FIOLog-$(date +"%m%d%Y-%H%M%S")/
mkdir $HOMEDIR/FIOLog
LOGDIR="${HOMEDIR}/FIOLog"

if [ $DISTRO_NAME == "sles" ] && [[ $DISTRO_VERSION =~ 12 ]]; then
	mdVolume="/dev/md/mdauto0"
else
	mdVolume="/dev/md0"
fi
vggroup="vg1"
cd ${HOMEDIR}

install_fio

if [ $? -ne 0 ]; then
	LogMsg "Error: install fio failed"
	UpdateTestState "TestAborted"
	exit 1
fi

if [[ $(detect_linux_distribution) == coreos ]]; then
	Delete_Containers
	fio_cmd="docker run -v $HOMEDIR/FIOLog/jsonLog:$HOMEDIR/FIOLog/jsonLog --device ${mdVolume} lisms/fio"
	iostat_cmd="docker run --network host lisms/toolbox iostat"
else
	fio_cmd="fio"
	iostat_cmd="iostat"
fi

#Creating RAID before triggering test
CreateRAID0
#CreateLVM

#Run test from here
LogMsg "*********INFO: Starting test execution*********"
RunFIO
LogMsg "*********INFO: Script execution reach END. Completed !!!*********"
