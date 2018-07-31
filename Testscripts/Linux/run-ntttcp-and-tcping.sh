#!/bin/bash
########################################################################
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
########################################################################
	log_folder=$1
	server_ip=$2
	server_username=$3
	test_run_duration=$4
	max_server_threads=64
	eth_name=$5
	test_threads_collection="$6"

	if [[ $log_folder == ""  ]]; then
		log_folder="nettestlogs-$(date  +'%Y%m%d-%H%M')"
	fi

	if [[ $server_ip == ""  ]]; then
		server_ip=192.168.4.113
	fi


	if [[ $server_username == ""  ]]; then
		server_username=root
	fi

	if [ "$(which ntttcp)" == "" ]; then
		rm -rf ntttcp-for-linux
		git clone https://github.com/Microsoft/ntttcp-for-linux
		cd ntttcp-for-linux/src || return
		make && make install
		cd ../..
	fi

	if [ "$(which lagscope)" == "" ]; then
		rm -rf lagscope
		git clone https://github.com/Microsoft/lagscope
		cd lagscope/src || return
		make && make install
		cd ../..
	fi

	eth_log="./$log_folder/eth_report.log"
	apt -y install bc sysstat dstat htop nload
	ssh $server_username@$server_ip "apt -y install bc sysstat dstat htop nload"

	function get_tx_bytes() {
		# RX bytes:66132495566 (66.1 GB)  TX bytes:3067606320236 (3.0 TB)
		Tx_bytes=$(ifconfig $eth_name | grep "TX bytes"   | awk -F':' '{print $3}' | awk -F' ' ' {print $1}')

		if [ "x$Tx_bytes" == "x" ]; then
			#TX packets 223558709  bytes 15463202847 (14.4 GiB)
			Tx_bytes=$(ifconfig $eth_name| grep "TX packets"| awk '{print $5}')
		fi
		echo "$Tx_bytes"
	}

	function get_tx_pkts() {
		# TX packets:543924452 errors:0 dropped:0 overruns:0 carrier:0
		Tx_pkts=$(ifconfig $eth_name | grep "TX packets" | awk -F':' '{print $2}' | awk -F' ' ' {print $1}')

		if [ "x$Tx_pkts" == "x" ]; then
			#TX packets 223558709  bytes 15463202847 (14.4 GiB)
			Tx_pkts=$(ifconfig $eth_name| grep "TX packets"| awk '{print $3}')
		fi
		echo $Tx_pkts
	}

	mkdir "$log_folder"
	ssh $server_username@$server_ip "ulimit -n 20480"
	ssh $server_username@$server_ip "mkdir $log_folder"

	rm -rf "$eth_log"
	echo "#test_connections    throughput_gbps    average_packet_size" > "$eth_log"

	previous_tx_bytes=$(get_tx_bytes)
	previous_tx_pkts=$(get_tx_pkts)
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

		echo "======================================"
		echo "Running Test: $num_threads_P X $num_threads_n"
		echo "======================================"

		ssh $server_username@$server_ip "for i in {1..$test_run_duration}; do ss -ta | grep ESTA | grep -v ssh | wc -l >> \
        ./$log_folder/tcp-connections-p${num_threads_P}X${num_threads_n}.log; sleep 1; done" &

		ssh $server_username@$server_ip "pkill -f ntttcp"
		ssh $server_username@$server_ip "ulimit -n 204800 && ntttcp -P $num_threads_P -t ${test_run_duration} -e > \
        ./$log_folder/ntttcp-receiver-p${num_threads_P}X${num_threads_n}.log" &

		ssh $server_username@$server_ip "pkill -f lagscope"
		ssh $server_username@$server_ip "lagscope -r" &

		ssh $server_username@$server_ip "pkill -f dstat"
		ssh $server_username@$server_ip "dstat -dam > ./$log_folder/dstat-receiver-p${num_threads_P}X${num_threads_n}.log" &

		ssh $server_username@$server_ip "pkill -f mpstat"
		ssh $server_username@$server_ip "mpstat -P ALL 1 ${test_run_duration} > ./$log_folder/mpstat-receiver-p${num_threads_P}X${num_threads_n}.log" &

		ulimit -n 204800
		sleep 2
		sar -n DEV 1 "${test_run_duration}" > "./$log_folder/sar-sender-p${num_threads_P}X${num_threads_n}.log" &
		dstat -dam > "./$log_folder/dstat-sender-p${num_threads_P}X${num_threads_n}.log" &
		mpstat -P ALL 1 "${test_run_duration}" > "./$log_folder/mpstat-sender-p${num_threads_P}X${num_threads_n}.log" &
		lagscope -s$server_ip -t "${test_run_duration}" -V > "./$log_folder/lagscope-ntttcp-p${num_threads_P}X${num_threads_n}.log" &
		ntttcp -s${server_ip} -P $num_threads_P -n $num_threads_n -t "${test_run_duration}"  > \
        "./$log_folder/ntttcp-sender-p${num_threads_P}X${num_threads_n}.log"

		current_tx_bytes=$(get_tx_bytes)
		current_tx_pkts=$(get_tx_pkts)
		bytes_new=$((current_tx_bytes-previous_tx_bytes))
		pkts_new=$((current_tx_pkts-previous_tx_pkts))
		avg_pkt_size=$(echo "scale=2;$bytes_new/$pkts_new/1024" | bc)
		throughput=$(echo "scale=2;$bytes_new/$test_run_duration*8/1024/1024/1024" | bc)
		previous_tx_bytes=$current_tx_bytes
		previous_tx_pkts=$current_tx_pkts

		echo "throughput (gbps): $throughput"
		echo "average packet size: $avg_pkt_size"
		printf "%4s  %8.2f  %8.2f\\n" "${current_test_threads}" "$throughput" "$avg_pkt_size" >> "$eth_log"

		echo "current test finished. wait for next one... "
		i=$((i + 1))
		sleep 5
	done

	pkill -f dstat
	ssh $server_username@$server_ip "pkill -f dstat"
	ssh $server_username@$server_ip "pkill -f ntttcp"
	ssh $server_username@$server_ip "pkill -f lagscope"

	echo "all done."