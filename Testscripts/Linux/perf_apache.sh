#!/bin/bash

#######################################################################
#
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
#######################################################################

#######################################################################
#
# perf_apache.sh
# Description:
#    Install apache and run apache performance tests.
#    This script needs to be run on client VM.
#
# Supported Distros:
#    Ubuntu/Suse/Centos/RedHat/Debian
#######################################################################
CONSTANTS_FILE="./constants.sh"
UTIL_FILE="./utils.sh"

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

if [ ! "${CONCURRENCIES}" ]; then
	CONCURRENCIES=(1 2 4 8 16 32 64 128 256 512 1024)
fi

if [ ! "${max_concurrency_per_ab}" ]; then
	max_concurrency_per_ab=4
fi

if [ ! "${max_ab_instances}" ]; then
	max_ab_instances=16
fi

# Install apache on client and server Machine
LogMsg "Configuring client ${client}..."
install_apache
if [ $? -ne 0 ]; then
	LogMsg "Error: apache installation failed in ${client}.."
	SetTestStateAborted
	exit 0
fi

LogMsg "Configuring server ${server}..."
Run_SSHCommand "${server}" ". $UTIL_FILE && install_apache"
if [ $? -ne 0 ]; then
	LogMsg "Error: apache installation failed in ${server}.."
	SetTestStateAborted
	exit 0
fi

GetDistro
case "$DISTRO_NAME" in
	oracle|rhel|centos)
		web_server="httpd"
		document_path="/var/www/html/test.dat"
		;;

	ubuntu|debian)
		web_server="apache2"
		document_path="/var/www/html/test.dat"
		;;

	sles|suse)
		web_server="apache2"
		document_path="/srv/www/htdocs/test.dat"
		;;
	*)
		LogErr "Unsupported distribution for apache test"
		SetTestStateSkipped
		exit 0
esac

mpstat_cmd="mpstat"
dstat_cmd="dstat"
sar_cmd="sar"
vmstat_cmd="vmstat"

testName="apache"
log_folder="$(pwd)/${testName}-test-logs"
result_file="${log_folder}/report.csv"
timeout=500

Start_Monitor()
{
	current_concurrency=${1}
	Run_SSHCommand "${server}" "pkill -f dstat"
	Run_SSHCommand "${server}" "pkill -f mpstat"
	Run_SSHCommand "${server}" "pkill -f sar"
	Run_SSHCommand "${server}" "pkill -f vmstat"
	Run_SSHCommand "${server}" "${dstat_cmd} -dam" > "${log_folder}/${current_concurrency}.dstat.server.log" &
	Run_SSHCommand "${server}" "${sar_cmd} -n DEV 1" > "${log_folder}/${current_concurrency}.sar.server.log" &
	Run_SSHCommand "${server}" "${mpstat_cmd} -P ALL 1" > "${log_folder}/${current_concurrency}.mpstat.server.log" &
	Run_SSHCommand "${server}" "${vmstat_cmd} 1" > "${log_folder}/${current_concurrency}.vmstat.server.log" &

	pkill -f dstat
	pkill -f mpstat
	pkill -f sar
	pkill -f vmstat
	${dstat_cmd} -dam > ${log_folder}/${current_concurrency}.dstat.client.log &
	${sar_cmd} -n DEV 1 > ${log_folder}/${current_concurrency}.sar.client.log &
	${mpstat_cmd} -P ALL 1 > ${log_folder}/${current_concurrency}.mpstat.client.log &
	${vmstat_cmd} 1 > ${log_folder}/${current_concurrency}.vmstat.client.log &
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

Run_ab()
{
	current_concurrency=${1}

	if [ ${current_concurrency} -le 2 ]
	then
		total_requests=50000
	elif [ ${current_concurrency} -le 128 ]
	then
		total_requests=100000
	else
		total_requests=200000
	fi

	ab_instances=$(($current_concurrency / $max_concurrency_per_ab))
	if [ ${ab_instances} -eq 0 ]
	then
		ab_instances=1
	fi
	if [ ${ab_instances} -gt ${max_ab_instances} ]
	then
		ab_instances=${max_ab_instances}
	fi

	total_request_per_ab=$(($total_requests / $ab_instances))
	concurrency_per_ab=$(($current_concurrency / $ab_instances))
	concurrency_left=${current_concurrency}
	requests_left=${total_requests}
	while [ ${concurrency_left} -gt ${max_concurrency_per_ab} ]; do
		concurrency_left=$(($concurrency_left - $concurrency_per_ab))
		requests_left=$(($requests_left - $total_request_per_ab))
		LogMsg "Running parallel ab command for: ${total_request_per_ab} X ${concurrency_per_ab}"
		ab -n ${total_request_per_ab} -r -c ${concurrency_per_ab} -s $timeout http://${server}/test.dat >> ${log_folder}/${current_concurrency}.${testName}.bench.log & pid=$!
		PID_LIST+=" $pid"
	done

	if [ ${concurrency_left} -gt 0 ]
	then
		LogMsg "Running parallel ab command left for: ${requests_left} X ${concurrency_left}"
		ab -n ${requests_left} -r -c ${concurrency_left} -s $timeout http://${server}/test.dat >> ${log_folder}/${current_concurrency}.${testName}.bench.log & pid=$!
		PID_LIST+=" $pid";
	fi
	trap "kill ${PID_LIST}" SIGINT
	wait ${PID_LIST}
}

Run_apache()
{
	Run_SSHCommand "${server}" "pkill -f ab"
	pkill -f ab

	# Restart apache2 service
	LogMsg "Info: Generate test data file on the Apache server ${document_path}"
	Run_SSHCommand "${server}" "dd if=/dev/urandom of=${document_path} bs=1K count=200"
	Run_SSHCommand "${server}" "service ${web_server} stop"
	Run_SSHCommand "${server}" "service ${web_server} start"

	Run_SSHCommand "${server}" "rm -rf ${log_folder}"
	Run_SSHCommand "${server}" "mkdir -p ${log_folder}"
	rm -rf ${log_folder}
	mkdir -p ${log_folder}

	echo "WebServerVersion,Concurrencies,NumberOfAbInstances,ConcurrencyPerAbInstance,Document_bytes,\
CompleteRequests,RequestsPerSec,TransferRate_KBps,MeanConnectionTimes_ms" > "${result_file}"

	for current_concurrency in "${CONCURRENCIES[@]}"; do
		LogMsg "Running apache_bench test with current concurrency: ${current_concurrency}"

		Start_Monitor ${current_concurrency}
		Run_ab ${current_concurrency}
		Stop_Monitor
		sleep 5

		# Parse log
		apache_log_file="${log_folder}/${current_concurrency}.${testName}.bench.log"
		WebServerVersion=$(grep "Server Software:" "$apache_log_file" | head -n1 | tr ":" " " | awk '{print $NF}')
		concurrency=$(grep "Concurrency Level:" "$apache_log_file" | head -n1 | tr ":" " " | awk '{print $NF}')
		documentLength=$(grep "Document Length" "$apache_log_file" | head -n1 | tr ":" " " | awk '{print $3}')
		requests=$(grep "Complete requests:" "$apache_log_file" | tr ":" " " | awk '{print $NF}' | awk 'BEGIN{} {sum+=$1} END {print sum}')
		numOfAb=$(grep "Complete requests:" "$apache_log_file" | wc -l)
		req_sec=$(grep "Requests per second:" "$apache_log_file" | tr ":" " " | awk '{print $4}' | awk 'BEGIN{} {sum+=$1} END {print sum}')
		transfer=$(grep "Transfer rate:" "$apache_log_file" | tr ":" " " | awk '{print $3}' | awk 'BEGIN{sum=0.0} {sum+=$1} END {print float sum}')
		meanTime=$(grep "Total:" "$apache_log_file" | tr ":" " " | awk '{print $3}' | awk 'BEGIN{} {sum+=$1} END {print sum/NR}')

		LogMsg "Test Results: "
		LogMsg "---------------"
		LogMsg "WebServerVersion: $WebServerVersion"
		LogMsg "Test Concurrency: $current_concurrency"
		LogMsg "Number Of AbInstances: $numOfAb"
		LogMsg "Concurrency Per AbInstance: $concurrency"
		LogMsg "Document Length: $documentLength"
		LogMsg "Complete Requests: $requests"
		LogMsg "Requests Per Sec: $req_sec"
		LogMsg "Transfer Rate(KBps): $transfer"
		LogMsg "Mean Connection Times (ms): $meanTime"

		echo "$WebServerVersion,$current_concurrency,$numOfAb,$concurrency,$documentLength,$requests,$req_sec,$transfer,$meanTime" >> "${result_file}"
	done
}

# Start the Apache client on client VM
LogMsg "Now running Apache test"
Run_apache

column -s, -t "${result_file}" > "${log_folder}"/report.log
cp "${log_folder}"/* .
cat report.log
SetTestStateCompleted
