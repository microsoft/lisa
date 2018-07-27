#!/bin/bash
########################################################################
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
########################################################################
	log_folder=$1
	ntttcp_log_prefix="ntttcp-sender-p"
	lagscope_log_prefix="lagscope-ntttcp-p"
	test_threads_collection="$2"
	max_server_threads=64
	result_file="${log_folder}/report.log"

	if [[ $log_folder == ""  ]]; then
		echo "please specify a log folder"
		exit
	fi

	function get_throughput() {
		throuput="Empty"
		while read -r line
		do
			if [[ "$line" == *"throughput"* ]]; then
				if [[ "$line" == *"Gbps"* ]]; then
					temp1=$(echo "$line" | awk -F'\t:' '{print $2}' | sed 's/Gbps//')
				elif [[ "$line" == *"Mbps"* ]]; then
					temp1m=$(echo "$line" | awk -F'\t:' '{print $2}' | sed 's/Mbps//')
					temp1=$(echo "scale=3; $temp1m/1000" | bc)
				fi
				echo "$temp1"
				throuput="NotEmpty"
			fi
		done < "$1"

		if [ "$throuput" == "Empty" ]; then
			echo 0
		fi
	}

	function get_cyclesperbyte() {
		while read -r line
		do
			if [[ "$line" == *"cycles/byte"* ]]; then
				echo "$line" | awk -F'\t:' '{print $2}'
			fi
		done < "$1"
	}

	function get_latency() {
		average="Empty"
		while read -r line
		do
			if [[ "$line" == *"Average"* ]]; then
				temp2=$(echo "$line" | awk -F'=' '{print $4}' | awk -F'us' '{print $1}')
				echo "$temp2"
				average="NotEmpty"
			fi
		done < "$1"
		
		if [ "$average" == "Empty" ]; then
			echo 0
		fi
	}

	echo "#test_connections throughput_gbps cycles/bytes    average_tcp_latency" > "$result_file"
	i=0
	
	for current_test_threads in $test_threads_collection; do
		#current_test_threads=${test_threads_collection[$i]}
		if [ "$current_test_threads" -lt "$max_server_threads" ]; then
			num_threads_P=$current_test_threads
			num_threads_n=1
		else
			num_threads_P=$max_server_threads
			num_threads_n=$((current_test_threads / num_threads_P))
		fi

		ntttcp_log_file="$log_folder/${ntttcp_log_prefix}${num_threads_P}X${num_threads_n}.log"
		lagscope_log_file="$log_folder/${lagscope_log_prefix}${num_threads_P}X${num_threads_n}.log"

		throughput=$(get_throughput "$ntttcp_log_file")
		cyclesperbytes=$(get_cyclesperbyte "$ntttcp_log_file")
		latency=$(get_latency "$lagscope_log_file")

		if  [ "x$throughput" == "x" ]; then
			throughput=0
		fi

		if  [ "x$cyclesperbytes" == "x" ]; then
			cyclesperbytes=0
		fi

		if [ "x$latency" == "x" ]; then
			latency=0
		fi

		printf "%4s  %8.2f %8.2f %8.2f\\n" "${current_test_threads}" "${throughput}" "${cyclesperbytes}" "${latency}" >> "$result_file"

		i=$((i + 1))
	done

	cat "$result_file"