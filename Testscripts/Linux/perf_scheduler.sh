#!/bin/bash
#######################################################################
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
# perf_scheduler.sh
# Description:
#    Download and run hackbench and schbench test
# Supported Distros:
#    Ubuntu, SUSE, RedHat, CentOS
#######################################################################
HOMEDIR=$(pwd)
UTIL_FILE="./utils.sh"
LOG_FOLDER="${HOMEDIR}/scheduler_log"
HACKBENCH_RESULT="${LOG_FOLDER}/results_hackbench.csv"
SCHBENCH_RESULT="${LOG_FOLDER}/results_schbench.csv"
SCHBENCH_DIR="${HOMEDIR}/schbench"

HACKBENCH_TYPE=("process.pipe" "process.socket" "thread.pipe" "thread.socket")

mkdir -p $LOG_FOLDER

. ${UTIL_FILE} || {
	LogErr "Missing ${UTIL_FILE} file"
	SetTestStateAborted
	exit 0
}

#Schbench
THREADS=$(grep -c ^processor /proc/cpuinfo)
if [ ! "${MSG_THREADS}" ]; then
	MSG_THREADS=(6 12)
fi
if [ ! "${RUNTIME}" ]; then
	RUNTIME=300
fi
if [ ! "${SLEEPTIME}" ]; then
	SLEEPTIME=30000
fi
if [ ! "${CPUTIME}" ]; then
	CPUTIME=30000
fi

# hackbench
if [ ! "${DATASIZE}" ]; then
	DATASIZE=(128 256 512 1024 2048 4096)
fi
if [ ! "${LOOPS}" ]; then
	LOOPS=2000
fi
GROUP_NR=$(grep -c ^processor /proc/cpuinfo)
# If the number of FD is bigger,the time of running this test is much longer. We set the FDS 32 
FDS=25

# Install hackbench and schbench required packages
function install_dependency_package () {
	LogMsg "Detected $DISTRO_NAME $DISTRO_VERSION; installing required packages of hackbench and schbench"
	update_repos
	case "$DISTRO_NAME" in
		oracle|rhel|centos)
			install_epel
			install_package "sysstat zip make gcc git numactl numactl-devel git"
			;;
		ubuntu|debian)
			install_package "sysstat zip make gcc libnuma-dev git "
			;;
		sles|suse)
			if [[ $DISTRO_VERSION =~ 12|15 ]]; then				
				install_package "sysstat zip make gcc libnuma-devel git"
			else
				LogErr "Unsupported SLES version"
				return 1
			fi
			;;
		*)
			LogErr "Unsupported distribution"
			return 1
	esac
	if [ $? -ne 0 ]; then
		return 1
	fi
}

function build_hackbench () {
	pkgVer=1.8
	source="https://www.kernel.org/pub/linux/utils/rt-tests/rt-tests-${pkgVer}.tar.gz"
	wget $source
	tar -zxvf rt-tests-${pkgVer}.tar.gz
	cd rt-tests-${pkgVer}
	make && make install
	if [ $? -ne 0 ]; then
		LogErr "Build hackbench failed."
		SetTestStateAborted
		exit 0
	fi
	cd ..
	export PATH=$PATH:/usr/local/bin
}

function build_schbench () {
	git clone https://git.kernel.org/pub/scm/linux/kernel/git/mason/schbench.git
	cd ./schbench
	make
	if [ $? -ne 0 ]; then
		LogErr "Build schbench failed."
		SetTestStateAborted
		exit 0
	fi
	cd ..
}

function start_monitor () {
	name=${1}
	type=${2}
	vmstat 1 2>&1 > /${LOG_FOLDER}/${name}.${type}.vmstat.log 2>&1 & 
	sar -P ALL 1 2>&1 > /${LOG_FOLDER}/${name}.${type}.sar.cpu.log 2>&1 &
}

function stop_monitor () {
	pkill -f vmstat
	pkill -f sar
}

function run_hackbench () {
#   -p, --pipe Sends the data via a pipe instead of the socket (default)
#   -s, --datasize=<size in bytes> Sets the amount of data to send in each message
#   -l, --loops=<number of loops> How many messages each sender/receiver pair should send
#   -g, --groups=<number of groups> Defines how many groups  of  senders  and  receivers  should  be started
#   -f, --fds=<number of file descriptors> Defines  how  many file descriptors each child should use
#   -T, --threads Each sender/receiver child will be a POSIX thread of the parent.
#   -P, --process Hackbench will use fork() on all children (default behaviour)
	dataSize=${1}
	LogMsg "hackbench with process mode start running with $GROUP_NR sender and receiver groups, sending the data via a pipe"
	type="${dataSize}.process.pipe"
	start_monitor "hackbench" "${type}"
	hackbench -s ${dataSize} -l ${LOOPS} -g ${GROUP_NR} -f ${FDS} -P -p > /${LOG_FOLDER}/hackbench.${type}.log 2>&1
	check_exit_status "Run hackbench" "failed"
	stop_monitor
	sleep 5

	LogMsg "hackbench with thread mode start running with $GROUP_NR sender and receiver groups, sending the data via a pipe"
	type="${dataSize}.thread.pipe"
	start_monitor "hackbench" "${type}"
	hackbench -s ${dataSize} -l ${LOOPS} -g ${GROUP_NR} -f ${FDS} -T -p > /${LOG_FOLDER}/hackbench.${type}.log 2>&1
	check_exit_status "Run hackbench" "failed"
	stop_monitor
	sleep 5

	LogMsg "hackbench with process mode start running with $GROUP_NR sender and receiver groups, sending the data via socket"
	type="${dataSize}.process.socket"
	start_monitor "hackbench" "${type}"
	hackbench -s ${dataSize} -l ${LOOPS} -g ${GROUP_NR} -f ${FDS} -P > /${LOG_FOLDER}/hackbench.${type}.log 2>&1
	check_exit_status "Run hackbench" "failed"
	stop_monitor
	sleep 5

	LogMsg "hackbench with thread mode start running with $GROUP_NR sender and receiver groups, sending the data via socket"
	type="${dataSize}.thread.socket"
	start_monitor "hackbench" "${type}"
	hackbench -s ${dataSize} -l ${LOOPS} -g ${GROUP_NR} -f ${FDS} -T > /${LOG_FOLDER}/hackbench.${type}.log 2>&1
	check_exit_status "Run hackbench" "failed"
	stop_monitor
	sleep 5
}

function run_schbench () {
#    -m (--message-threads): number of message threads (def: 2)
#    -t (--threads): worker threads per message thread (def: 16)
#    -r (--runtime): How long to run before exiting (seconds, def: 30)
#    -s (--sleeptime): Message thread latency (usec, def: 10000
#    -c (--cputime): How long to think during loop (usec, def: 10000
#    -a (--auto): grow thread count until latencies hurt (def: off)
#    -p (--pipe): transfer size bytes to simulate a pipe test (def: 0)
#    -R (--rps): requests per second mode (count, def: 0)
	currentMsgThreads=$1
	LogMsg "schbench start running with $currentMsgThreads message threads."
	start_monitor "schbench" "${currentMsgThreads}"
	./schbench -c ${CPUTIME} -s ${SLEEPTIME} -m ${currentMsgThreads} -t ${THREADS} -r ${RUNTIME} > /${LOG_FOLDER}/schbench.${currentMsgThreads}.log 2>&1
	check_exit_status "Run schbench" "failed"
	stop_monitor
	sleep 5
}

function parse_hackbench_log () {
	echo "TestMode,DataSize_bytes,Loops,Groups,FDS,HackbenchType,Latency_sec" > "${HACKBENCH_RESULT}"
	for type in "${HACKBENCH_TYPE[@]}"
	do
		for datasize in "${DATASIZE[@]}"
		do
			hackbench_log_file="${LOG_FOLDER}/hackbench.${datasize}.${type}.log"
			latency=$(grep "Time:" "$hackbench_log_file" | tr ":" " " | awk '{print $NF}')
			LogMsg "Test Results: "
			LogMsg "---------------"
			LogMsg "TestMode: hackbench"
			LogMsg "DataSize_bytes: $datasize"
			LogMsg "Loops: $LOOPS"
			LogMsg "Groups: $GROUP_NR"
			LogMsg "FDS: $FDS"
			LogMsg "HackbenchType: $type"
			LogMsg "Latency(seconds): $latency"
			echo "hackbench,$datasize,$LOOPS,$GROUP_NR,$FDS,$type,$latency" >> "${HACKBENCH_RESULT}"
		done
	done
}

function parse_schbench_log () {
	echo "TestMode,WorkerThreads,MessageThreads,Latency95thPercentile_us,Latency99thPercentile_us" > "${SCHBENCH_RESULT}"
	for msg in "${MSG_THREADS[@]}"
	do
		schbench_log_file="${LOG_FOLDER}/schbench.${msg}.log"
		latency95=$(grep "95.0th:" "$schbench_log_file" | tr ":" " " | awk '{print $NF}')
		latency99=$(grep "99.0th:" "$schbench_log_file" | tr ":" " " | awk '{print $NF}')
		LogMsg "Test Results: "
		LogMsg "---------------"
		LogMsg "TestMode: schbench"
		LogMsg "WorkerThreads: $THREADS"
		LogMsg "MessageThreads: $msg"
		LogMsg "Latency of 95th Percentile(us): $latency95"
		LogMsg "Latency of 99th Percentile(us): $latency99"
		echo "schbench,$THREADS,$msg,$latency95,$latency99" >> "${SCHBENCH_RESULT}"
	done
}
###############################################################################
#
# Main script body
#
###############################################################################
LogMsg "Install required packages..."
install_dependency_package
if [ $? -ne 0 ]; then
	LogErr "Dependency packages installation failed"
	SetTestStateAborted
	exit 0
fi

LogMsg "Build hackbench..."
build_hackbench

LogMsg "Run hackbench..."
for datasize in "${DATASIZE[@]}"
do
	run_hackbench $datasize
done
parse_hackbench_log

LogMsg "Build schbench..."
build_schbench

LogMsg "Run schbench..."
cd ${SCHBENCH_DIR}
for msg in "${MSG_THREADS[@]}"
do
    run_schbench ${msg}
done
cd $HOMEDIR
parse_schbench_log

column -s, -t "${HACKBENCH_RESULT}" > "${LOG_FOLDER}"/results_hackbench.log
column -s, -t "${SCHBENCH_RESULT}" > "${LOG_FOLDER}"/results_schbench.log
cat "${LOG_FOLDER}"/results_hackbench.log
cat "${LOG_FOLDER}"/results_schbench.log

cp "${LOG_FOLDER}"/* .
SetTestStateCompleted
