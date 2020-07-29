#!/bin/bash

#######################################################################
#
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
#######################################################################

#######################################################################
#
# perf_memcached.sh
# Description:
#    Install memcached and run memcached performance tests.
#    This script needs to be run on client VM.
#
# Supported Distros:
#    Ubuntu/Suse/Centos/RedHat/Debian
#######################################################################
CONSTANTS_FILE="./constants.sh"
UTIL_FILE="./utils.sh"

PORT="21789"

. ${CONSTANTS_FILE} || {
	errMsg="Error: missing ${CONSTANTS_FILE} file"
	LogMsg "${errMsg}"
	UpdateTestState $ICA_TESTABORTED
	exit 0
}

. ${UTIL_FILE} || {
	LogErr "Missing ${UTIL_FILE} file"
	SetTestStateAborted
	exit 0
}

if [ ! "${server}" ]; then
	LogErr "Please add/provide value for server in constants.sh. server=<server ip>"
	SetTestStateAborted
	exit 0
fi
if [ ! "${client}" ]; then
	LogErr "Please add/provide value for client in constants.sh. client=<client ip>"
	SetTestStateAborted
	exit 0
fi

if [ ! "${nicName}" ]; then
	LogErr "Please add/provide value for nicName in constants.sh. nicName=eth0/bond0"
	SetTestStateAborted
	exit 0
fi

if [ ! "${THREADS}" ]; then
	THREADS=(1 2 4 8 16 32 64 128 256 512)
fi

if [ ! "${max_threads}" ]; then	
	max_threads=16
fi

# Install memcached on client and server Machine
LogMsg "Configuring client ${client}..."
install_memcached
if [ $? -ne 0 ]; then
	LogMsg "Error: memcached installation failed in ${client}.."
	SetTestStateAborted
	exit 0
fi

LogMsg "Configuring server ${server}..."
Run_SSHCommand "${server}" ". $UTIL_FILE && install_memcached"
if [ $? -ne 0 ]; then
	LogMsg "Error: memcached installation failed in ${server}.."
	SetTestStateAborted
	exit 0
fi

mpstat_cmd="mpstat"
dstat_cmd="dstat"
sar_cmd="sar"
vmstat_cmd="vmstat"

testName="memcached"
log_folder="$(pwd)/${testName}-test-logs"
result_file="${log_folder}/report.csv"

Build_Memtier()
{
	git clone https://github.com/RedisLabs/memtier_benchmark
	cd ./memtier_benchmark
	git checkout 1.3.0
	autoreconf -ivf; ./configure; make; make install >> ${log_folder}/${testName}.build.log
	cd ../
}

Start_Monitor()
{
	lteration=${1}
	Run_SSHCommand "${server}" "pkill -f dstat"
	Run_SSHCommand "${server}" "pkill -f mpstat"
	Run_SSHCommand "${server}" "pkill -f sar"
	Run_SSHCommand "${server}" "pkill -f vmstat"
	Run_SSHCommand "${server}" "${dstat_cmd} -dam" > "${log_folder}/${lteration}.dstat.server.log" &
	Run_SSHCommand "${server}" "${sar_cmd} -n DEV 1" > "${log_folder}/${lteration}.sar.server.log" &
	Run_SSHCommand "${server}" "${mpstat_cmd} -P ALL 1" > "${log_folder}/${lteration}.mpstat.server.log" &
	Run_SSHCommand "${server}" "${vmstat_cmd} 1" > "${log_folder}/${lteration}.vmstat.server.log" &

	pkill -f dstat
	pkill -f mpstat
	pkill -f sar
	pkill -f vmstat
	${dstat_cmd} -dam > ${log_folder}/${lteration}.dstat.server.log &
	${sar_cmd} -n DEV 1 > ${log_folder}/${lteration}.sar.server.log &
	${mpstat_cmd} -P ALL 1 > ${log_folder}/${lteration}.mpstat.server.log &
	${vmstat_cmd} 1 > ${log_folder}/${lteration}.vmstat.server.log &
}

Stop_Monitor()
{
	Run_SSHCommand "${server}" "pkill -f dstat"
	Run_SSHCommand "${server}" "pkill -f mpstat"
	Run_SSHCommand "${server}" "pkill -f sar"
	Run_SSHCommand "${server}" "pkill -f vmstat"
	pkill -f dstat
	pkill -f mpstat
	pkill -f sar
	pkill -f vmstat
}

Run_Memcached()
{
	testThread=$1
	num_threads=$2
	num_client_per_thread=$3
	total_request=$4

	LogMsg "======================================"
	LogMsg "Running Test: ${testThread} = ${num_threads} X ${num_client_per_thread}"
	LogMsg "======================================"

	Start_Monitor $testThread

	Run_SSHCommand "${client}" "memtier_benchmark -s ${server} -p ${PORT} -P memcache_text -x 3 -n ${total_request} -t ${num_threads} -c ${num_client_per_thread} -d 4000 --ratio 1:1 --key-pattern S:S > ${log_folder}/${testThread}.${testName}.bench.log"

	Stop_Monitor
	sleep 5

	# Parse log
	memcached_log_file="${log_folder}/${testThread}.${testName}.bench.log"
	Threads=$(grep "Threads" $memcached_log_file | awk '{print $1}')
	ConnectionsPerThread=$(grep "Connections per thread" $memcached_log_file | awk '{print $1}')
	RequestsPerThread=$(grep "Requests per client" $memcached_log_file | awk '{print $1}')
	BestOpsPerSec=$(grep "BEST RUN RESULTS" $memcached_log_file -A7 | grep "Totals" | awk '{print $2}')
	BestLatency_ms=$(grep "BEST RUN RESULTS" $memcached_log_file -A7 | grep "Totals" | awk '{print $5}')
	WorstOpsPerSec=$(grep "WORST RUN RESULTS" $memcached_log_file -A7 | grep "Totals" | awk '{print $2}')
	WorstLatency_ms=$(grep "WORST RUN RESULTS" $memcached_log_file -A7 | grep "Totals" | awk '{print $5}')
	AverageOpsPerSec=$(grep "AGGREGATED AVERAGE RESULTS" $memcached_log_file -A7 | grep "Totals" | awk '{print $2}')
	AverageLatency_ms=$(grep "AGGREGATED AVERAGE RESULTS" $memcached_log_file -A7 | grep "Totals" | awk '{print $5}')

	LogMsg "Test Results: "
	LogMsg "---------------"
	LogMsg "Threads: $Threads"
	LogMsg "Connections Per Thread: $ConnectionsPerThread"
	LogMsg "Requests Per Thread: $RequestsPerThread"
	LogMsg "Best Ops Per Sec: $BestOpsPerSec"
	LogMsg "Best Latency_ms: $BestLatency_ms"
	LogMsg "Worst Ops Per Sec: $WorstOpsPerSec"
	LogMsg "Worst Latency_ms: $WorstLatency_ms"
	LogMsg "Average Ops Per Sec: $AverageOpsPerSec"
	LogMsg "Average Latency_ms: $AverageLatency_ms"

	echo "$testThread,$Threads,$ConnectionsPerThread,$RequestsPerThread,$BestLatency_ms,$WorstLatency_ms,\
$AverageLatency_ms,$BestOpsPerSec,$WorstOpsPerSec,$AverageOpsPerSec" >> "${result_file}"
}

Run_SSHCommand "${server}" "rm -rf ${log_folder}"
Run_SSHCommand "${server}" "mkdir -p ${log_folder}"
Run_SSHCommand "${server}" "pkill -f memcached"
rm -rf ${log_folder}
mkdir -p ${log_folder}

LogMsg "Starting memcached server on ${server}"
Run_SSHCommand "${server}" "memcached -u "root" -p ${PORT}" &

echo "TestConnections,Threads,ConnectionsPerThread,RequestsPerThread,BestLatency_ms,WorstLatency_ms,\
AverageLatency_ms,BestOpsPerSec,WorstOpsPerSec,AverageOpsPerSec" > "${result_file}"

Build_Memtier
# Start the Memcached client on client VM
LogMsg "Now running Memcached test"
for thread in "${THREADS[@]}"
do
	if [ ${thread} -lt ${max_threads} ]
	then
		num_threads=${thread}
		num_client_per_thread=1
		total_request=1000000
	else
		num_threads=${max_threads}
		num_client_per_thread=$((${thread} / ${num_threads}))
		total_request=100000
	fi
	Run_Memcached ${thread} ${num_threads} ${num_client_per_thread} ${total_request}
done

LogMsg "Kernel Version : $(uname -r)"
LogMsg "Guest OS : ${distro}"

column -s, -t "${result_file}" > "${log_folder}"/report.log
cp "${log_folder}"/* .
cat report.log
SetTestStateCompleted
