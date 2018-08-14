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
LogMsg "Test start..."
CONSTANTS_FILE="$HOMEDIR/constants.sh"
UTIL_FILE="$HOMEDIR/utils.sh"
ICA_TESTRUNNING="TestRunning"      # The test is running
ICA_TESTCOMPLETED="TestCompleted"  # The test completed successfully
ICA_TESTABORTED="TestAborted"      # Error during the setup of the test
ICA_TESTFAILED="TestFailed"        # Error occurred during the test
touch ./fioTest.log

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
	echo "${1}" > $HOMEDIR/state.txt
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
				echo "-- iteration ${iteration} ----------------------------- ${testmode} test, ${io}K bs, ${Thread} threads, ${numjobs} jobs, 5 minutes ------------------ $(date +"%x %r %Z") ---" >> $LOGFILE
				LogMsg "Running ${testmode} test, ${io}K bs, ${Thread} threads ..."
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
	rm fiodata

	compressedFileName="${HOMEDIR}/FIOTest-$(date +"%m%d%Y-%H%M%S").tar.gz"
	LogMsg "INFO: Please wait...Compressing all results to ${compressedFileName}..."
	tar -cvzf $compressedFileName $LOGDIR/

	echo "Test logs are located at ${LOGDIR}"
	UpdateTestState ICA_TESTCOMPLETED
}

############################################################
#	Main body
############################################################

#Creating RAID before triggering test
scp /root/CreateRaid.sh root@nfs-server-vm:
ssh root@nfs-server-vm "chmod +x /root/CreateRaid.sh"
ssh root@nfs-server-vm "/root/CreateRaid.sh"

if [ $? -eq 0 ]; then
	HOMEDIR=$HOME
	mv $HOMEDIR/FIOLog/ $HOMEDIR/FIOLog-$(date +"%m%d%Y-%H%M%S")/
	mkdir $HOMEDIR/FIOLog
	LOGDIR="${HOMEDIR}/FIOLog"

	if [ $DISTRO_NAME == "sles" ] && [[ $DISTRO_VERSION =~ 12 ]]; then
		mdVolume="/dev/md/mdauto0"
	else
		mdVolume="/dev/md0"
	fi
	mountDir="/data"
	cd ${HOMEDIR}
	install_fio
	install_package "nfs-common"

	#Start NFS Server
	ssh root@nfs-server-vm "apt update"
	ssh root@nfs-server-vm "apt install -y nfs-kernel-server"
	ssh root@nfs-server-vm "echo '/data nfs-client-vm(rw,sync,no_root_squash)' >> /etc/exports"
	ssh root@nfs-server-vm "service nfs-kernel-server restart"
	#Mount NFS Directory.
	mkdir -p ${mountDir}
	mount -t nfs -o proto=${nfsprotocol},vers=3  nfs-server-vm:${mountDir} ${mountDir}
	if [ $? -eq 0 ]; then
		LogMsg "*********INFO: Starting test execution*********"
		cd ${mountDir}
		mkdir sampleDIR
		RunFIO
		LogMsg "*********INFO: Script execution reach END. Completed !!!*********"
	else
		LogMsg "Failed to mount NSF directory."
	fi
	#Run test from here

else
	LogMsg "Error: Unable to Create RAID on NSF server"
	exit 1
fi


