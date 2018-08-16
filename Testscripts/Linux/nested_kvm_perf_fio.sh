#!/bin/bash

#######################################################################
#
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
#######################################################################

#######################################################################
#
# nested_kvm_perf_io.sh
#
# Description:
#   This script runs fio test on nested VMs with one or multiple data disk
#
#######################################################################

HOMEDIR="/root"
log_msg()
{
	echo "[$(date +"%x %r %Z")] ${1}"
	echo "[$(date +"%x %r %Z")] ${1}" >> "${HOMEDIR}/runlog.txt"
}
log_msg "Sleeping 10 seconds.."
sleep 10

CONSTANTS_FILE="$HOMEDIR/constants.sh"
UTIL_FILE="$HOMEDIR/utils.sh"
ICA_TESTRUNNING="TestRunning"      # The test is running
ICA_TESTCOMPLETED="TestCompleted"  # The test completed successfully
ICA_TESTABORTED="TestAborted"      # Error during the setup of the test
ICA_TESTFAILED="TestFailed"        # Error occurred during the test
touch ./fioTest.log

. ${CONSTANTS_FILE} || {
	errMsg="Error: missing ${CONSTANTS_FILE} file"
	log_msg "${errMsg}"
	update_test_state $ICA_TESTABORTED
	exit 10
}
. ${UTIL_FILE} || {
	errMsg="Error: missing ${UTIL_FILE} file"
	log_msg "${errMsg}"
	update_test_state $ICA_TESTABORTED
	exit 10
}


update_test_state()
{
	echo "${1}" > $HOMEDIR/state.txt
}
run_fio()
{
	update_test_state $ICA_TESTRUNNING

	####################################
	#All run config set here
	#

	#Log Config
	
	mkdir $HOMEDIR/FIOLog/jsonLog
	mkdir $HOMEDIR/FIOLog/iostatLog
	mkdir $HOMEDIR/FIOLog/blktraceLog

	JSONFILELOG="${LOGDIR}/jsonLog"
	IOSTATLOGDIR="${LOGDIR}/iostatLog"
	BLKTRACELOGDIR="${LOGDIR}/blktraceLog"
	LOGFILE="${LOGDIR}/fio-test.log.txt"	

	#redirect blktrace files directory
	Resource_mount=$(mount -l | grep /sdb1 | awk '{print$3}')
	blk_base="${Resource_mount}/blk-$(date +"%m%d%Y-%H%M%S")"
	mkdir $blk_base
	#Test config
	iteration=0
	io_increment=128

	####################################
	echo "Test log created at: ${LOGFILE}"
	echo "===================================== Starting Run $(date +"%x %r %Z") ================================"
	echo "===================================== Starting Run $(date +"%x %r %Z") script generated 2/9/2015 4:24:44 PM ================================" >> $LOGFILE

	chmod 666 $LOGFILE
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
				echo "-- iteration ${iteration} ----------------------------- ${testmode} test, ${io}K bs, ${Thread} threads, ${numjobs} jobs, 5 minutes ------------------ $(date +"%x %r %Z") ---" >> $LOGFILE
				log_msg "Running ${testmode} test, ${io}K bs, ${Thread} threads ..."
				jsonfilename="${JSONFILELOG}/fio-result-${testmode}-${io}K-${Thread}td.json"
				fio $FILEIO --readwrite=$testmode --bs=${io}K --runtime=$ioruntime --iodepth=$Thread --numjobs=$numjobs --output-format=json --output=$jsonfilename --name="iteration"${iteration} >> $LOGFILE
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

	compressedFileName="${HOMEDIR}/FIOTest-$(date +"%m%d%Y-%H%M%S").tar.gz"
	log_msg "INFO: Please wait...Compressing all results to ${compressedFileName}..."
	tar -cvzf $compressedFileName $LOGDIR/

	echo "Test logs are located at ${LOGDIR}"
	update_test_state $ICA_TESTCOMPLETED
}

remove_raid_and_format()
{
	disks=$(ls -l /dev | grep sd[b-z]$ | awk '{print $10}')

	log_msg "INFO: Check and remove RAID first"
	mdvol=$(cat /proc/mdstat | grep md | awk -F: '{ print $1 }')
	if [ -n "$mdvol" ]; then
		log_msg "/dev/${mdvol} already exist...removing first"
		umount /dev/${mdvol}
		mdadm --stop /dev/${mdvol}
		mdadm --remove /dev/${mdvol}
	fi
	for disk in ${disks}
	do
		log_msg "formatting disk /dev/${disk}"
		mkfs -t ext4 -F /dev/${disk}
	done
}

create_raid0()
{
	disks=$(ls -l /dev | grep sd[b-z]$ | awk '{print $10}')	
	log_msg "INFO: Creating Partitions"
	count=0
	for disk in ${disks}
	do		
		log_msg "Partition disk /dev/${disk}"
		(echo d; echo n; echo p; echo 1; echo; echo; echo t; echo fd; echo w;) | fdisk /dev/${disk}
		count=$(( $count + 1 ))
		sleep 1
	done
	log_msg "INFO: Creating RAID of ${count} devices."
	sleep 1
	yes | mdadm --create ${mdVolume} --level 0 --raid-devices ${count} /dev/sd[b-z][1-5]
	sleep 1
	if [ $? -ne 0 ]; then
		update_test_state "$ICA_TESTFAILED"
		log_msg "Error: unable to create raid ${mdVolume}"
		exit 1
	else
		log_msg "Raid ${mdVolume} create successfully."
	fi
	log_msg "formatting ${mdVolume}"
	time mkfs -t $1 -F ${mdVolume}
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

cd ${HOMEDIR}

install_fio
remove_raid_and_format

if [[ $RaidOption == 'RAID in L2' ]]; then
	#For RAID in L2
	create_raid0 ext4
	devices=$mdVolume
	disks='md0'
else
	#For RAID in L1, No RAID and single disk
	devices=''
	disks=($(ls -l /dev | grep sd[b-z]$ | awk '{print $10}'))
	for disk in ${disks[@]}
	do
		if [[ $devices == '' ]]; then
			devices="/dev/${disk}"
		else
			devices="${devices}:/dev/${disk}"
		fi
	done
fi

for disk in ${disks[@]}
do
	log_msg "set rq_affinity to 0 for device ${disk}"
	echo 0 > /sys/block/${disk}/queue/rq_affinity
done

log_msg "*********INFO: Starting test execution*********"

FILEIO="--size=${fileSize} --direct=1 --ioengine=libaio --filename=${devices} --overwrite=1"
log_msg "FIO common parameters: ${FILEIO}"
run_fio

log_msg "*********INFO: Script execution reach END. Completed !!!*********"