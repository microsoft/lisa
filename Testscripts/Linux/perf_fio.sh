#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
# In this script, we want to bench-mark device IO performance on a mounted folder.
# You can adapt this script to other situations easily like for stripe disks as RAID0.
# The only thing to keep in mind is that each different configuration you're testing
# must log its output to a different directory.

HOMEDIR="/root"
LogMsg()
{
	echo "[$(date +"%x %r %Z")] ${1}"
	echo "[$(date +"%x %r %Z")] ${1}" >> "${HOMEDIR}/runlog.txt"
}

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
	if [ $type == "disk" ]; then
		mdVolume="/dev/sdc"
	fi
	FILEIO="--size=${fileSize} --direct=1 --ioengine=libaio --filename=${mdVolume} --overwrite=1 "
	if [ -n "${NVME}" ]; then
		FILEIO="--direct=1 --ioengine=libaio --filename=${nvme_namespaces} --gtod_reduce=1"
	fi
	iteration=0
	io_increment=128
	if [ $type == "disk" ]; then
		NUM_JOBS=(1 1 2 2 4 4)
	else
		NUM_JOBS=(1 1 2 2 4 4 8 8 8 8 8 8)
	fi

	# Log Config
	mkdir $HOMEDIR/FIOLog/jsonLog
	mkdir $HOMEDIR/FIOLog/iostatLog
	mkdir $HOMEDIR/FIOLog/blktraceLog

	# LOGDIR="${HOMEDIR}/FIOLog"
	JSONFILELOG="${LOGDIR}/jsonLog"
	IOSTATLOGDIR="${LOGDIR}/iostatLog"
	LOGFILE="${LOGDIR}/fio-test.log.txt"

	# redirect blktrace files directory
	Resource_mount=$(mount -l | grep /sdb1 | awk '{print$3}')
	blk_base="${Resource_mount}/blk-$(date +"%m%d%Y-%H%M%S")"
	mkdir $blk_base

	####################################
	LogMsg "Test log created at: ${LOGFILE}"
	LogMsg "===================================== Starting Run $(date +"%x %r %Z") ================================"

	chmod 666 $LOGFILE
	LogMsg "--- Kernel Version Information ---"
	uname -a >> $LOGFILE
	cat /proc/version >> $LOGFILE
	if [ -f /usr/share/clear/version ]; then
		cat /usr/share/clear/version >> $LOGFILE
	elif [[ -n $(ls /etc/*-release) ]]; then
		cat /etc/*-release >> $LOGFILE
	fi
	LogMsg "--- PCI Bus Information ---"
	lspci >> $LOGFILE
	df -h >> $LOGFILE
	fio --cpuclock-test >> $LOGFILE
	####################################
	# Trigger run from here
	for testmode in "${modes[@]}"; do
		io=$startIO
		while [ $io -le $maxIO ]
		do
			numJobIterator=0
			qDepth=$startQDepth
			while [ $qDepth -le $maxQDepth ]
			do
				numJob=${NUM_JOBS[$numJobIterator]}
				if [ -z "$numJob" ]; then
					numJob=${NUM_JOBS[-1]}
				fi
				if [ -n "${NVME}" ]; then
					# NVMe perf tests requires that numJob param should match the vCPU number
					numJob=$(nproc)
				fi
				thread=$((qDepth/numJob))

				iostatfilename="${IOSTATLOGDIR}/iostat-fio-${testmode}-${io}K-${thread}td.txt"
				nohup $iostat_cmd -x 5 -t -y > $iostatfilename &
				LogMsg "-- iteration ${iteration} ----------------------------- ${testmode} test, ${io}K bs, ${thread} threads, ${numJob} jobs, 5 minutes ------------------ $(date +"%x %r %Z") ---"
				LogMsg "Running ${testmode} test, ${io}K bs, ${qDepth} qdepth (${thread} X ${numJob})..."
				jsonfilename="${JSONFILELOG}/fio-result-${testmode}-${io}K-${qDepth}td.json"
				LogMsg "${fio_cmd} $FILEIO --readwrite=${testmode} --bs=${io}K --runtime=${ioruntime} --iodepth=${thread} --numjob=${numJob} --output-format=json --output=${jsonfilename} --name='iteration'${iteration}"
				$fio_cmd $FILEIO --readwrite=$testmode --bs=${io}K --runtime=$ioruntime --iodepth=$thread --numjob=$numJob --output-format=json --output=$jsonfilename --name="iteration"${iteration} >> $LOGFILE 2>&1
				if [ $? -ne 0 ]; then
					LogMsg "Error: Failed to run fio"
					UpdateTestState $ICA_TESTFAILED
					compressedFileName="${HOMEDIR}/FIOTest-$(date +"%m%d%Y-%H%M%S").tar.gz"
					LogMsg "INFO: Please wait...Compressing all results to ${compressedFileName}..."
					tar -cvzf $compressedFileName $LOGDIR/
					exit 1
				fi
				iostatPID=$(ps -ef | awk '/iostat/ && !/awk/ { print $2 }')
				kill -9 $iostatPID
				qDepth=$((qDepth*2))
				iteration=$((iteration+1))
				numJobIterator=$((numJobIterator+1))
				if [[ $(detect_linux_distribution) == coreos ]]; then
					Kill_Process 127.0.0.1 fio
				fi
			done
		io=$((io * io_increment))
		done
	done
	####################################
	LogMsg "===================================== Completed Run at $(date +"%x %r %Z") ================================"

	compressedFileName="${HOMEDIR}/FIOTest-$(date +"%m%d%Y-%H%M%S").tar.gz"
	LogMsg "INFO: Please wait...Compressing all results to ${compressedFileName}..."
	tar -cvzf $compressedFileName $LOGDIR/

	LogMsg "Test logs are located at ${LOGDIR}"
	UpdateTestState $ICA_TESTCOMPLETED
}

RunStressFIO()
{
	UpdateTestState $ICA_TESTRUNNING
	FILEIO="--size=${fileSize} --direct=1 --ioengine=libaio --filename=${mdVolume} --overwrite=1 "
	if [ -n "${NVME}" ]; then
		FILEIO="--direct=1 --ioengine=libaio --filename=${nvme_namespaces} --gtod_reduce=1"
	fi
	iteration=0
	io_increment=4

	# Log Config
	mkdir $HOMEDIR/FIOLog/jsonLog
	mkdir $HOMEDIR/FIOLog/iostatLog
	mkdir $HOMEDIR/FIOLog/blktraceLog

	# LOGDIR="${HOMEDIR}/FIOLog"
	JSONFILELOG="${LOGDIR}/jsonLog"
	IOSTATLOGDIR="${LOGDIR}/iostatLog"
	LOGFILE="${LOGDIR}/fio-test.log.txt"

	# redirect blktrace files directory
	Resource_mount=$(mount -l | grep /sdb1 | awk '{print$3}')
	blk_base="${Resource_mount}/blk-$(date +"%m%d%Y-%H%M%S")"
	mkdir $blk_base

	####################################
	LogMsg "Test log created at: ${LOGFILE}"
	LogMsg "===================================== Starting Run $(date +"%x %r %Z") ================================"

	chmod 666 $LOGFILE
	LogMsg "--- Kernel Version Information ---"
	uname -a >> $LOGFILE
	cat /proc/version >> $LOGFILE
	if [ -f /usr/share/clear/version ]; then
		cat /usr/share/clear/version >> $LOGFILE
	elif [[ -n $(ls /etc/*-release) ]]; then
		cat /etc/*-release >> $LOGFILE
	fi
	LogMsg "--- PCI Bus Information ---"
	lspci >> $LOGFILE
	df -h >> $LOGFILE
	fio --cpuclock-test >> $LOGFILE
	####################################
	# Trigger run from here
	io=$startIO
	while [ $io -le $maxIO ]
	do
		numJobIterator=0
		qDepth=$startQDepth
		while [ $qDepth -le $maxQDepth ]
		do
			numJob=1
			thread=$((qDepth/numJob))
			for testmode in "${modes[@]}"; do
				iostatfilename="${IOSTATLOGDIR}/iostat-fio-${testmode}-${io}K-${thread}td.txt"
				nohup $iostat_cmd -x 5 -t -y > $iostatfilename &
				LogMsg "-- iteration ${iteration} ----------------------------- ${testmode} test, ${io}K bs, ${thread} threads, ${numJob} jobs ------------------ $(date +"%x %r %Z") ---"
				LogMsg "Running ${testmode} test, ${io}K bs, ${qDepth} qdepth (${thread} X ${numJob})..."
				jsonfilename="${JSONFILELOG}/fio-result-${testmode}-${io}K-${qDepth}td.json"
				if [[ "$testType" == "StressLongTime" ]] && [[ -n "$ioSize" ]]; then
					if [ -z "${testmode##*'write'*}" ]; then
						LogMsg "${fio_cmd} $FILEIO --readwrite=${testmode} --bs=${io}K --iodepth=${thread} --numjobs=${numJob} --output-format=json --output=${jsonfilename} --gtod_reduce=1 --runtime=${ioruntime}  --io_size=$ioSize --name='iteration'${iteration} --verify=md5 --iodepth_batch=32 --verify_dump=1"
						$fio_cmd $FILEIO --readwrite=$testmode --bs=${io}K --iodepth=$thread --numjobs=$numJob --output-format=json --output=$jsonfilename --gtod_reduce=1 --runtime=$ioruntime --io_size=$ioSize --name="iteration"${iteration} --verify=md5 --iodepth_batch=32 --verify_dump=1 >> $LOGFILE 2>&1
					fi
				else
					if [ -z "${testmode##*'write'*}" ]; then
						LogMsg "${fio_cmd} $FILEIO --readwrite=${testmode} --bs=${io}K --iodepth=${thread} --numjob=${numJob} --output-format=json --output=${jsonfilename} --name='iteration'${iteration} --verify=sha1 --do_verify=0 --verify_backlog=1024 --verify_fatal=1"
						$fio_cmd $FILEIO --readwrite=$testmode --bs=${io}K --iodepth=$thread --numjobs=$numJob --output-format=json --output=$jsonfilename --name="iteration"${iteration} --verify=sha1 --do_verify=0 --verify_backlog=1024 --verify_fatal=1 --verify_dump=1 >> $LOGFILE 2>&1
					else
						LogMsg "${fio_cmd} $FILEIO --readwrite=${testmode} --bs=${io}K --iodepth=${thread} --numjob=${numJob} --output-format=json --output=${jsonfilename} --name='iteration'${iteration} --verify=sha1 --do_verify=1 --verify_backlog=1024 --verify_fatal=1 --verify_only"
						$fio_cmd $FILEIO --readwrite=$testmode --bs=${io}K --iodepth=$thread --numjobs=$numJob --output-format=json --output=$jsonfilename --name="iteration"${iteration} --verify=sha1 --do_verify=1 --verify_backlog=1024 --verify_fatal=1 --verify_only --verify_dump=1 >> $LOGFILE 2>&1
					fi
				fi
				if [ $? -ne 0 ]; then
					LogMsg "Error: Failed to run fio in verify phase"
					UpdateTestState $ICA_TESTFAILED
					compressedFileName="${HOMEDIR}/FIOTest-$(date +"%m%d%Y-%H%M%S").tar.gz"
					LogMsg "INFO: Please wait...Compressing all results to ${compressedFileName}..."
					tar -cvzf $compressedFileName $LOGDIR/
					exit 1
				fi

				iostatPID=$(ps -ef | awk '/iostat/ && !/awk/ { print $2 }')
				kill -9 $iostatPID
				if [[ $(detect_linux_distribution) == coreos ]]; then
					Kill_Process 127.0.0.1 fio
				fi
			done
			qDepth=$((qDepth*2))
			iteration=$((iteration+1))
			numJobIterator=$((numJobIterator+1))
		done
	io=$((io * io_increment))
	done
	####################################
	LogMsg "===================================== Completed Run at $(date +"%x %r %Z") ================================"

	compressedFileName="${HOMEDIR}/FIOTest-$(date +"%m%d%Y-%H%M%S").tar.gz"
	LogMsg "INFO: Please wait...Compressing all results to ${compressedFileName}..."
	tar -cvzf $compressedFileName $LOGDIR/

	LogMsg "Test logs are located at ${LOGDIR}"
	UpdateTestState $ICA_TESTCOMPLETED
}

CreateRAID0()
{
	disks=$(get_AvailableDisks)
	diskLetters=$(echo "$disks" | sed 's/sd//g' | tr -d '\n')

	LogMsg "INFO: Check and remove RAID first"
	mdvol=$(cat /proc/mdstat | grep active | awk {'print $1'})
	if [ -n "$mdvol" ]; then
		LogMsg "/dev/${mdvol} already exist...removing first"
		umount /dev/${mdvol}
		mdadm --stop /dev/${mdvol}
		mdadm --remove /dev/${mdvol}
		mdadm --zero-superblock /dev/sd[a-z][1-5]
	fi

	LogMsg "INFO: Creating Partitions"
	count=0
	for disk in ${disks}
	do
		LogMsg "formatting disk /dev/${disk}"
		(echo d; echo n; echo p; echo 1; echo; echo; echo t; echo fd; echo w;) | fdisk /dev/${disk}
		count=$(($count + 1))
		sleep 1
	done
	LogMsg "INFO: Creating RAID of ${count} devices."
	sleep 1
	if [ -n "$chunkSize" ]; then
		mdadm --create ${mdVolume} --level 0 --chunk $chunkSize --raid-devices ${count} /dev/sd["$diskLetters"][1-5]
	else
		mdadm --create ${mdVolume} --level 0 --raid-devices ${count} /dev/sd["$diskLetters"][1-5]
	fi

	if [ -n "$fileSystem" ]; then
		mkfs -t $fileSystem ${mdVolume}
	fi
}

ConfigNVME()
{
	install_nvme_cli
	namespace_list=$(ls -l /dev | grep -w nvme[0-9]n[0-9]$ | awk '{print $10}')
	nvme_namespaces=""
	for namespace in ${namespace_list}; do
		nvme format /dev/${namespace}
		sleep 1
		(echo d; echo w) | fdisk /dev/${namespace}
		sleep 1
		echo 0 > /sys/block/${namespace}/queue/rq_affinity
		sleep 1
		nvme_namespaces="${nvme_namespaces}/dev/${namespace}:"
		LogMsg "NMVe name space: $namespace"
	done
	# Deleting last char of string (:)
	nvme_namespaces=${nvme_namespaces%?}

	# Set the remaining variables
	# NVMe perf tests will have a starting qdepth equal to vCPU number
	startQDepth=$(nproc)
	LogMsg "Setting qdepth in the setting: $startQDepth"
	# NVMe perf tests will have a max qdepth equal to vCPU number x 256
	maxQDepth=$(($(nproc) * 256))
	LogMsg "Setting maxQDepth in the setting: $maxQDepth"
}

CreateLVM()
{
	disks=$(ls -l /dev | grep sd[c-z]$ | awk '{print $10}')
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
# Main body
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

# Creating RAID before triggering test
if [ -n "${NVME}" ]; then
	ConfigNVME
else
	CreateRAID0
fi

# Run test from here
LogMsg "*********INFO: Starting test execution*********"
if [[ "$testType" == "Stress" ]] || [[ "$testType" == "StressLongTime" ]];then
	RunStressFIO
else
	RunFIO
fi
LogMsg "*********INFO: Script execution reach END. Completed !!!*********"
