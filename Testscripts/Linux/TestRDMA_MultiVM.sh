#!/bin/bash
#
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
# This script will run Infiniband test.
# To run this script following things are must.
# 1. constants.sh
# 2. passwordless authentication is setup in all VMs in current cluster.
# 3. All VMs in cluster have infiniband hardware.
# 4. Intel MPI binaries are installed in VM. If not, download and install trial version from :
#    https://software.intel.com/en-us/intel-mpi-library
# 5. VHD is prepared for Infiniband tests.

########################################################################################################
# Source utils.sh
. utils.sh || {
	echo "Error: unable to source utils.sh!"
	echo "TestAborted" > state.txt
	exit 0
}

# Source constants file and initialize most common variables
UtilsInit

imb_mpi1_final_status=0
imb_rma_final_status=0
imb_nbc_final_status=0
imb_p2p_final_status=0
imb_io_final_status=0
omb_p2p_final_status=0

# Get all the Kernel-Logs from all VMs.
function Collect_Logs() {
	slaves_array=$(echo ${slaves} | tr ',' ' ')
	for vm in $master $slaves_array; do
		LogMsg "Getting kernel logs from $vm"
		ssh root@${vm} "dmesg > kernel-logs-${vm}.txt"
		scp root@${vm}:kernel-logs-${vm}.txt .
		if [ $? -eq 0 ]; then
			LogMsg "Kernel Logs collected successfully from ${vm}."
		else
			LogErr "Failed to collect kernel logs from ${vm}."
		fi
	done

	# Create zip file to avoid downloading thousands of files in some cases
	zip -r /root/IMB_AllTestLogs.zip /root/IMB-*
	rm -rf /root/IMB-*
	if [[ $benchmark_type == "OMB" ]]; then
		zip -r /root/OMB_AllTestLogs.zip /root/OMB-*
		rm -rf /root/OMB-*
	fi
}

function Run_IMB_Intranode() {
	# Verify Intel MPI PingPong Tests (IntraNode).
	final_mpi_intranode_status=0

	for vm1 in $master $slaves_array; do
		# Manual running needs to clean up the old log files.
		if [ -f ./IMB-MPI1-IntraNode-output-$vm1.txt ]; then
			rm -f ./IMB-MPI1-IntraNode-output-$vm1*.txt
			LogMsg "Removed the old log files"
		fi
		for vm2 in $master $slaves_array; do
			log_file=IMB-MPI1-IntraNode-output-$vm1-$vm2.txt
			LogMsg "Checking IMB-MPI1 IntraNode status in $vm1"
			retries=0
			while [ $retries -lt 3 ]; do
				case "$mpi_type" in
					ibm)
						LogMsg "$mpi_run_path -hostlist $vm1:1,$vm2:1 -np 2 -e MPI_IB_PKEY=$MPI_IB_PKEY -ibv $imb_ping_pong_path 4096"
						ssh root@${vm1} "$mpi_run_path -hostlist $vm1:1,$vm2:1 -np 2 -e MPI_IB_PKEY=$MPI_IB_PKEY -ibv $imb_ping_pong_path 4096 >> $log_file"
					;;
					open)
						LogMsg "$mpi_run_path --allow-run-as-root $non_shm_mpi_settings -np 2 --host $vm1,$vm2 $imb_mpi1_path pingpong"
						ssh root@${vm1} "$mpi_run_path --allow-run-as-root $non_shm_mpi_settings -np 2 --host $vm1,$vm2 $imb_mpi1_path pingpong >> $log_file"
					;;
					hpcx)
						if [ "$vm1" != "$vm2" ]; then
							hpcx_init=$(find / -name hpcx-init.sh | grep root)
							mpivars=$(find / -name mpivars.sh | grep open)
							LogMsg "$mpi_run_path --allow-run-as-root -x UCX_IB_PKEY=$UCX_IB_PKEY $non_shm_mpi_settings -n 2 --H $vm1,$vm2 $imb_mpi1_path pingpong"
							ssh root@${vm1} "source $hpcx_init; source $mpivars; hpcx_load; $mpi_run_path --allow-run-as-root -x UCX_IB_PKEY=$UCX_IB_PKEY $non_shm_mpi_settings -n 2 --H $vm1,$vm2 $imb_mpi1_path pingpong >> $log_file"
						fi
					;;
					intel)
						LogMsg "$mpi_run_path -hosts $vm1,$vm2 -ppn 2 -n 2 $non_shm_mpi_settings $imb_mpi1_path pingpong"
						ssh root@${vm1} "$mpi_run_path -hosts $vm1,$vm2 -ppn 2 -n 2 $non_shm_mpi_settings $imb_mpi1_path pingpong >> $log_file"
					;;
					mvapich)
						LogMsg "$mpi_run_path -n 2 $vm1 $vm2 $imb_mpi1_path pingpong"
						ssh root@${vm1} "$mpi_run_path -n 2 $vm1 $vm2 $imb_mpi1_path pingpong >> $log_file"
					;;
				esac
				mpi_intranode_status=$?
				scp root@${vm1}:$log_file .
				if [ $mpi_intranode_status -eq 0 ]; then
					LogMsg "IMB-MPI1 IntraNode status in $vm1 - Succeeded."
					retries=4
				else
					sleep 10
					let retries=retries+1
				fi
			done
			if [ $mpi_intranode_status -ne 0 ]; then
				LogErr "IMB-MPI1 IntraNode status in $vm1 - Failed"
				final_mpi_intranode_status=$(($final_mpi_intranode_status + $mpi_intranode_status))
			fi
		done
	done

	if [ $final_mpi_intranode_status -ne 0 ]; then
		LogErr "IMB-MPI1 Intranode test failed in some VMs. Aborting further tests."
		SetTestStateFailed
		Collect_Logs
		LogErr "INFINIBAND_VERIFICATION_FAILED_IMB_MPI1_INTRANODE"
		exit 0
	else
		LogMsg "INFINIBAND_VERIFICATION_SUCCESS_IMB_MPI1_INTRANODE"
	fi
}

function Run_IMB_MPI1() {
	total_attempts=$(seq 1 1 $imb_mpi1_tests_iterations)
	if [[ $imb_mpi1_tests == "all" ]]; then
		extra_params=""
	else
		extra_params=$imb_mpi1_tests
	fi
	for attempt in $total_attempts; do
		LogMsg "IMB-MPI1 test iteration $attempt - Running."
		case "$mpi_type" in
			ibm)
				LogMsg "$mpi_run_path -hostlist $modified_slaves:$VM_Size -np $(($VM_Size * $total_virtual_machines)) -e MPI_IB_PKEY=$MPI_IB_PKEY $imb_mpi1_path allreduce"
				$mpi_run_path -hostlist $modified_slaves:$VM_Size -np $(($VM_Size * $total_virtual_machines)) -e MPI_IB_PKEY=$MPI_IB_PKEY $imb_mpi1_path allreduce > IMB-MPI1-AllNodes-output-Attempt-${attempt}.txt
			;;
			open)
				LogMsg "$mpi_run_path --allow-run-as-root --host $master,$slaves -n $(($mpi1_ppn * $total_virtual_machines)) $mpi_settings $imb_mpi1_path $extra_params"
				$mpi_run_path --allow-run-as-root --host $master,$slaves -n $(($mpi1_ppn * $total_virtual_machines)) $mpi_settings $imb_mpi1_path $extra_params > IMB-MPI1-AllNodes-output-Attempt-${attempt}.txt
			;;
			hpcx)
				LogMsg "$mpi_run_path --allow-run-as-root -x UCX_IB_PKEY=$UCX_IB_PKEY -n $(($mpi1_ppn * $total_virtual_machines)) --H $master,$slaves $mpi_settings $imb_mpi1_path $extra_params"
				$mpi_run_path --allow-run-as-root -x UCX_IB_PKEY=$UCX_IB_PKEY -n $(($mpi1_ppn * $total_virtual_machines)) --H $master,$slaves $mpi_settings $imb_mpi1_path $extra_params > IMB-MPI1-AllNodes-output-Attempt-${attempt}.txt
			;;
			intel)
				LogMsg "$mpi_run_path -hosts $master,$slaves -ppn $(($VM_Size / $total_virtual_machines)) -n $(($VM_Size * $total_virtual_machines)) $mpi_settings $imb_mpi1_path $extra_params"
				$mpi_run_path -hosts $master,$slaves -ppn $(($VM_Size / $total_virtual_machines)) -n $(($VM_Size * $total_virtual_machines)) $mpi_settings $imb_mpi1_path $extra_params > IMB-MPI1-AllNodes-output-Attempt-${attempt}.txt
			;;
			mvapich)
				LogMsg "$mpi_run_path -n $(($mpi1_ppn * $total_virtual_machines)) $master $slaves_array $mpi_settings $imb_mpi1_path $extra_params"
				$mpi_run_path -n $(($mpi1_ppn * $total_virtual_machines)) $master $slaves_array $mpi_settings $imb_mpi1_path $extra_params > IMB-MPI1-AllNodes-output-Attempt-${attempt}.txt
			;;
		esac
		mpi_status=$?
		if [ $mpi_status -eq 0 ]; then
			LogMsg "IMB-MPI1 test iteration $attempt - Succeeded."
			sleep 1
		else
			LogErr "IMB-MPI1 test iteration $attempt - Failed."
			imb_mpi1_final_status=$(($imb_mpi1_final_status + $mpi_status))
			sleep 1
		fi
	done

	if [ $imb_mpi1_final_status -ne 0 ]; then
		LogErr "IMB-MPI1 tests returned non-zero exit code."
		SetTestStateFailed
		Collect_Logs
		LogErr "INFINIBAND_VERIFICATION_FAILED_IMB_MPI1_ALLNODES"
		exit 0
	else
		LogMsg "INFINIBAND_VERIFICATION_SUCCESS_IMB_MPI1_ALLNODES"
	fi
}

function Run_OMB_P2P() {
	total_attempts=$(seq 1 1 $omb_p2p_tests_iterations)
	omb_p2p_tests_array=($omb_p2p_tests)
	for attempt in $total_attempts; do
		case "$mpi_type" in
			mvapich)
				LogMsg "OMB P2P test iteration $attempt for $mpi_type- Running."
				for test_name in ${omb_p2p_tests_array[@]}; do
					LogMsg "ssh root@${master} $mpi_run_path -n $total_virtual_machines $master $slaves_array $omb_mpi_settings  numactl $numactl_settings  $omb_path/mpi/pt2pt/$test_name> OMB-P2P-AllNodes-output-Attempt-${attempt}-$test_name.txt"
					ssh root@${master} "$mpi_run_path -n $total_virtual_machines $master $slaves_array $omb_mpi_settings numactl $numactl_settings $omb_path/mpi/pt2pt/$test_name> OMB-P2P-AllNodes-output-Attempt-${attempt}-$test_name.txt"
				done
			;;
			*)
				LogErr "Test not yet available"
			;;
		esac
		mpi_status=$?
		if [ $mpi_status -eq 0 ]; then
			LogMsg "OMB P2P test iteration $attempt - Succeeded."
		else
			LogErr "OMB P2P test iteration $attempt - Failed."
			omb_p2p_final_status=$(($omb_p2p_final_status + $mpi_status))
		fi
		sleep 1
	done

	if [ $omb_p2p_final_status -ne 0 ]; then
		LogErr "OMB P2P tests returned non-zero exit code."
		SetTestStateFailed
		Collect_Logs
		LogErr "INFINIBAND_VERIFICATION_FAILED_OMB_P2P_ALLNODES"
		exit 0
	else
		LogMsg "INFINIBAND_VERIFICATION_SUCCESS_OMB_P2P_ALLNODES"
	fi
}

function Run_IMB_RMA() {
	total_attempts=$(seq 1 1 $imb_rma_tests_iterations)
	if [[ $imb_rma_tests == "all" ]]; then
		extra_params=""
	else
		extra_params=$imb_rma_tests
	fi
	for attempt in $total_attempts; do
		LogMsg "IMB-RMA test iteration $attempt - Running."
		case "$mpi_type" in
			ibm)
				# RMA skipped for IBM
				# LogMsg "$mpi_run_path -hostlist $modified_slaves:$VM_Size -np $(($VM_Size * $total_virtual_machines)) -e MPI_IB_PKEY=$MPI_IB_PKEY $imb_rma_path allreduce"
				# $mpi_run_path -hostlist $modified_slaves:$VM_Size -np $(($VM_Size * $total_virtual_machines)) -e MPI_IB_PKEY=$MPI_IB_PKEY $imb_rma_path allreduce > IMB-RMA-AllNodes-output-Attempt-${attempt}.txt
			;;
			open)
				LogMsg "$mpi_run_path --allow-run-as-root --host $master,$slaves -n $(($rma_ppn * $total_virtual_machines)) $mpi_settings $imb_rma_path $extra_params"
				$mpi_run_path --allow-run-as-root --host $master,$slaves -n $(($rma_ppn * $total_virtual_machines)) $mpi_settings $imb_rma_path $extra_params > IMB-RMA-AllNodes-output-Attempt-${attempt}.txt
			;;
			hpcx)
				LogMsg "$mpi_run_path --allow-run-as-root -x UCX_IB_PKEY=$UCX_IB_PKEY -n $(($rma_ppn * $total_virtual_machines)) --H $master,$slaves $mpi_settings $imb_rma_path $extra_params"
				$mpi_run_path --allow-run-as-root -x UCX_IB_PKEY=$UCX_IB_PKEY -n $(($rma_ppn * $total_virtual_machines)) --H $master,$slaves $mpi_settings $imb_rma_path $extra_params > IMB-RMA-AllNodes-output-Attempt-${attempt}.txt
			;;
			intel)
				LogMsg "$mpi_run_path -hosts $master,$slaves -ppn $(($VM_Size / $total_virtual_machines)) -n $(($VM_Size * $total_virtual_machines)) $mpi_settings $imb_rma_path $extra_params"
				$mpi_run_path -hosts $master,$slaves -ppn $(($VM_Size / $total_virtual_machines)) -n $(($VM_Size * $total_virtual_machines)) $mpi_settings $imb_rma_path $extra_params > IMB-RMA-AllNodes-output-Attempt-${attempt}.txt
			;;
			mvapich)
				LogMsg "$mpi_run_path -n $(($rma_ppn * $total_virtual_machines)) $master $slaves_array $mpi_settings $imb_rma_path $extra_params"
				$mpi_run_path -n $(($rma_ppn * $total_virtual_machines)) $master $slaves_array $mpi_settings $imb_rma_path $extra_params > IMB-RMA-AllNodes-output-Attempt-${attempt}.txt
			;;
		esac
		rma_status=$?
		if [ $rma_status -eq 0 ]; then
			LogMsg "IMB-RMA test iteration $attempt - Succeeded."
			sleep 1
		else
			LogErr "IMB-RMA test iteration $attempt - Failed."
			imb_rma_final_status=$(($imb_rma_final_status + $rma_status))
			sleep 1
		fi
	done

	if [ $imb_rma_final_status -ne 0 ]; then
		LogErr "IMB-RMA tests returned non-zero exit code. Aborting further tests."
		SetTestStateFailed
		Collect_Logs
		LogErr "INFINIBAND_VERIFICATION_FAILED_IMB_RMA_ALLNODES"
		exit 0
	else
		LogMsg "INFINIBAND_VERIFICATION_SUCCESS_IMB_RMA_ALLNODES"
	fi
}

function Run_IMB_NBC() {
	total_attempts=$(seq 1 1 $imb_nbc_tests_iterations)
	if [[ $imb_nbc_tests == "all" ]]; then
		extra_params=""
	else
		extra_params=$imb_nbc_tests
	fi
	for attempt in $total_attempts; do
		retries=0
		while [ $retries -lt 3 ]; do
			case "$mpi_type" in
				ibm)
					LogMsg "$mpi_run_path -hostlist $modified_slaves:$VM_Size -np $(($VM_Size * $total_virtual_machines)) -e MPI_IB_PKEY=$MPI_IB_PKEY $imb_nbc_path $extra_params"
					$mpi_run_path -hostlist $modified_slaves:$VM_Size -np $(($VM_Size * $total_virtual_machines)) -e MPI_IB_PKEY=$MPI_IB_PKEY $imb_nbc_path $extra_params > IMB-NBC-AllNodes-output-Attempt-${attempt}.txt
				;;
				open)
					LogMsg "$mpi_run_path --allow-run-as-root --host $master,$slaves -n $(($nbc_ppn * $total_virtual_machines)) $mpi_settings $imb_nbc_path $extra_params"
					$mpi_run_path --allow-run-as-root --host $master,$slaves -n $(($nbc_ppn * $total_virtual_machines)) $mpi_settings $imb_nbc_path $extra_params > IMB-NBC-AllNodes-output-Attempt-${attempt}.txt
				;;
				hpcx)
					LogMsg "$mpi_run_path --allow-run-as-root -x UCX_IB_PKEY=$UCX_IB_PKEY -n $(($nbc_ppn * $total_virtual_machines)) --H $master,$slaves $mpi_settings $imb_nbc_path $extra_params"
					$mpi_run_path --allow-run-as-root -x UCX_IB_PKEY=$UCX_IB_PKEY -n $(($nbc_ppn * $total_virtual_machines)) --H $master,$slaves $mpi_settings $imb_nbc_path $extra_params > IMB-NBC-AllNodes-output-Attempt-${attempt}.txt
				;;
				intel)
					LogMsg "$mpi_run_path -hosts $master,$slaves -ppn $(($VM_Size / $total_virtual_machines)) -n $(($VM_Size * $total_virtual_machines)) $mpi_settings $imb_nbc_path $extra_params"
					$mpi_run_path -hosts $master,$slaves -ppn $(($VM_Size / $total_virtual_machines)) -n $(($VM_Size * $total_virtual_machines)) $mpi_settings $imb_nbc_path $extra_params > IMB-NBC-AllNodes-output-Attempt-${attempt}.txt
				;;
				mvapich)
					LogMsg "$mpi_run_path -n $(($nbc_ppn * $total_virtual_machines)) $master $slaves_array $mpi_settings $imb_nbc_path $extra_params"
					$mpi_run_path -n $(($nbc_ppn * $total_virtual_machines)) $master $slaves_array $mpi_settings $imb_nbc_path $extra_params > IMB-NBC-AllNodes-output-Attempt-${attempt}.txt
				;;
			esac
			nbc_status=$?
			if [ $nbc_status -eq 0 ]; then
				LogMsg "IMB-NBC test iteration $attempt - Succeeded."
				sleep 1
				retries=4
			else
				sleep 10
				let retries=retries+1
				failed_nbc=$(cat IMB-NBC-AllNodes-output-Attempt-${attempt}.txt | grep Benchmarking | tail -1| awk '{print $NF}')
				nbc_benchmarks=$(echo $nbc_benchmarks | sed "s/^.*${failed_nbc}//")
				extra_params=$nbc_benchmarks
			fi
		done
		if [ $nbc_status -eq 0 ]; then
			LogMsg "IMB-NBC test iteration $attempt - Succeeded."
			sleep 1
		else
			LogErr "IMB-NBC test iteration $attempt - Failed."
			imb_nbc_final_status=$(($imb_nbc_final_status + $nbc_status))
			sleep 1
		fi
	done

	if [ $imb_nbc_final_status -ne 0 ]; then
		LogErr "IMB-NBC tests returned non-zero exit code. Aborting further tests."
		SetTestStateFailed
		Collect_Logs
		LogErr "INFINIBAND_VERIFICATION_FAILED_IMB_NBC_ALLNODES"
		exit 0
	else
		LogMsg "INFINIBAND_VERIFICATION_SUCCESS_IMB_NBC_ALLNODES"
	fi
}

function Run_IMB_P2P() {
	total_attempts=$(seq 1 1 $imb_p2p_tests_iterations)
	if [[ $imb_p2p_tests == "all" ]]; then
		extra_params=""
	else
		extra_params=$imb_p2p_tests
	fi
	for attempt in $total_attempts; do
		retries=0
		while [ $retries -lt 3 ]; do
			case "$mpi_type" in
				ibm)
					LogMsg "$mpi_run_path -hostlist $modified_slaves:$VM_Size -np $(($VM_Size * $total_virtual_machines)) -e MPI_IB_PKEY=$MPI_IB_PKEY $imb_p2p_path $extra_params"
					$mpi_run_path -hostlist $modified_slaves:$VM_Size -np $(($VM_Size * $total_virtual_machines)) -e MPI_IB_PKEY=$MPI_IB_PKEY $imb_p2p_path $extra_params > IMB-P2P-AllNodes-output-Attempt-${attempt}.txt
				;;
				open)
					LogMsg "$mpi_run_path --allow-run-as-root --host $master,$slaves -n $(($p2p_ppn * $total_virtual_machines)) $mpi_settings $imb_p2p_path $extra_params"
					$mpi_run_path --allow-run-as-root --host $master,$slaves -n $(($p2p_ppn * $total_virtual_machines)) $mpi_settings $imb_p2p_path $extra_params > IMB-P2P-AllNodes-output-Attempt-${attempt}.txt
				;;
				hpcx)
					LogMsg "$mpi_run_path --allow-run-as-root -x UCX_IB_PKEY=$UCX_IB_PKEY -n $(($p2p_ppn * $total_virtual_machines)) --H $master,$slaves $mpi_settings $imb_p2p_path $extra_params"
					$mpi_run_path --allow-run-as-root -x UCX_IB_PKEY=$UCX_IB_PKEY -n $(($p2p_ppn * $total_virtual_machines)) --H $master,$slaves $mpi_settings $imb_p2p_path $extra_params > IMB-P2P-AllNodes-output-Attempt-${attempt}.txt
				;;
				intel)
					# LogMsg "$mpi_run_path -hosts $master,$slaves -ppn $(($VM_Size / $total_virtual_machines)) -n $(($VM_Size * $total_virtual_machines)) $mpi_settings $imb_p2p_path $extra_params"
					# $mpi_run_path -hosts $master,$slaves -ppn $(($VM_Size / $total_virtual_machines)) -n $(($VM_Size * $total_virtual_machines)) $mpi_settings $imb_p2p_path $extra_params > IMB-P2P-AllNodes-output-Attempt-${attempt}.txt
				;;
				mvapich)
					LogMsg "$mpi_run_path -n $(($p2p_ppn * $total_virtual_machines)) $master $slaves_array $mpi_settings $imb_p2p_path $extra_params"
					$mpi_run_path -n $(($p2p_ppn * $total_virtual_machines)) $master $slaves_array $mpi_settings $imb_p2p_path $extra_params > IMB-P2P-AllNodes-output-Attempt-${attempt}.txt
				;;
			esac
			p2p_status=$?
			if [ $p2p_status -eq 0 ]; then
				LogMsg "IMB-P2P test iteration $attempt - Succeeded."
				sleep 1
				retries=4
			else
				sleep 10
				let retries=retries+1
				failed_p2p=$(cat IMB-P2P-AllNodes-output-Attempt-${attempt}.txt | grep Benchmarking | tail -1| awk '{print $NF}')
				p2p_benchmarks=$(echo $p2p_benchmarks | sed "s/^.*${failed_p2p}//")
				extra_params=$p2p_benchmarks
			fi
		done
		if [ $p2p_status -eq 0 ]; then
			LogMsg "IMB-P2P test iteration $attempt - Succeeded."
			sleep 1
		else
			LogErr "IMB-P2P test iteration $attempt - Failed."
			imb_p2p_final_status=$(($imb_p2p_final_status + $p2p_status))
			sleep 1
		fi
	done

	if [ $imb_p2p_final_status -ne 0 ]; then
		LogErr "IMB-P2P tests returned non-zero exit code. Aborting further tests."
		SetTestStateFailed
		Collect_Logs
		LogErr "INFINIBAND_VERIFICATION_FAILED_IMB_P2P_ALLNODES"
		exit 0
	else
		LogMsg "INFINIBAND_VERIFICATION_SUCCESS_IMB_P2P_ALLNODES"
	fi
}

function Run_IMB_IO() {
	total_attempts=$(seq 1 1 $imb_io_tests_iterations)
	if [[ $imb_io_tests == "all" ]]; then
		extra_params=""
	else
		extra_params=$imb_io_tests
	fi
	for attempt in $total_attempts; do
		retries=0
		while [ $retries -lt 3 ]; do
			case "$mpi_type" in
				ibm)
					LogMsg "$mpi_run_path -hostlist $modified_slaves:$VM_Size -np $(($VM_Size * $total_virtual_machines)) -e MPI_IB_PKEY=$MPI_IB_PKEY $imb_io_path $extra_params"
					$mpi_run_path -hostlist $modified_slaves:$VM_Size -np $(($VM_Size * $total_virtual_machines)) -e MPI_IB_PKEY=$MPI_IB_PKEY $imb_io_path $extra_params > IMB-IO-AllNodes-output-Attempt-${attempt}.txt
				;;
				open)
					LogMsg "$mpi_run_path --allow-run-as-root --host $master,$slaves -n $(($io_ppn * $total_virtual_machines)) $mpi_settings $imb_io_path $extra_params"
					$mpi_run_path --allow-run-as-root --host $master,$slaves -n $(($io_ppn * $total_virtual_machines)) $mpi_settings $imb_io_path $extra_params > IMB-IO-AllNodes-output-Attempt-${attempt}.txt
				;;
				hpcx)
					LogMsg "$mpi_run_path --allow-run-as-root -x UCX_IB_PKEY=$UCX_IB_PKEY -n $(($io_ppn * $total_virtual_machines)) --H $master,$slaves $mpi_settings $imb_io_path $extra_params"
					$mpi_run_path --allow-run-as-root -x UCX_IB_PKEY=$UCX_IB_PKEY -n $(($io_ppn * $total_virtual_machines)) --H $master,$slaves $mpi_settings $imb_io_path $extra_params > IMB-IO-AllNodes-output-Attempt-${attempt}.txt
				;;
				intel)
					LogMsg "$mpi_run_path -hosts $master,$slaves -ppn $(($VM_Size / $total_virtual_machines)) -n $(($VM_Size * $total_virtual_machines)) $mpi_settings $imb_io_path $extra_params"
					$mpi_run_path -hosts $master,$slaves -ppn $(($VM_Size / $total_virtual_machines)) -n $(($VM_Size * $total_virtual_machines)) $mpi_settings $imb_io_path $extra_params > IMB-IO-AllNodes-output-Attempt-${attempt}.txt
				;;
				mvapich)
					LogMsg "$mpi_run_path -n $(($io_ppn * $total_virtual_machines)) $master $slaves_array $mpi_settings $imb_io_path $extra_params"
					$mpi_run_path -n $(($io_ppn * $total_virtual_machines)) $master $slaves_array $mpi_settings $imb_io_path $extra_params > IMB-IO-AllNodes-output-Attempt-${attempt}.txt
				;;
			esac
			io_status=$?
			if [ $io_status -eq 0 ]; then
				LogMsg "IMB-IO test iteration $attempt - Succeeded."
				sleep 1
				retries=4
			else
				sleep 10
				let retries=retries+1
				failed_io=$(cat IMB-IO-AllNodes-output-Attempt-${attempt}.txt | grep Benchmarking | tail -1| awk '{print $NF}')
				io_benchmarks=$(echo $io_benchmarks | sed "s/^.*${failed_io}//")
				extra_params=$io_benchmarks
			fi
		done
		if [ $io_status -eq 0 ]; then
			LogMsg "IMB-IO test iteration $attempt - Succeeded."
			sleep 1
		else
			LogErr "IMB-IO test iteration $attempt - Failed."
			imb_io_final_status=$(($imb_io_final_status + $io_status))
			sleep 1
		fi
	done

	if [ $imb_io_final_status -ne 0 ]; then
		LogErr "IMB-IO tests returned non-zero exit code. Aborting further tests."
		SetTestStateFailed
		Collect_Logs
		LogErr "INFINIBAND_VERIFICATION_FAILED_IMB_IO_ALLNODES"
		exit 0
	else
		LogMsg "INFINIBAND_VERIFICATION_SUCCESS_IMB_IO_ALLNODES"
	fi
}

function Main() {
	LogMsg "Restarting waagent for ib0 device loading"
	if [[ $DISTRO == "ubuntu"* ]]; then
		service walinuxagent restart
	else
		service waagent restart
	fi
	sleep 2

	LogMsg "Starting $mpi_type MPI tests..."

	# ############################################################################################################
	# This is common space for all three types of MPI testing
	# Verify if ib_nic got IP address on All VMs in current cluster.
	# ib_nic comes from constants.sh. where get those values from XML tags.
	final_ib_nic_status=0
	total_virtual_machines=0
	err_virtual_machines=0
	slaves_array=$(echo ${slaves} | tr ',' ' ')
	nbc_benchmarks="Ibcast Iallgather Iallgatherv Igather Igatherv Iscatter Iscatterv Ialltoall Ialltoallv Ireduce Ireduce_scatter Iallreduce Ibarrier"

	# [pkey code moved from SetupRDMA.sh to TestRDMA_MultiVM.sh]
	# It's safer to obtain pkeys in the test script because some distros
	# may require a reboot after the IB setup is completed
	# Find the correct partition key for IB communicating with other VM
	if [[ $is_nd == "no" ]]; then
		if [ -z ${MPI_IB_PKEY+x} ]; then
			firstkey=$(cat /sys/class/infiniband/mlx5_0/ports/1/pkeys/0)
			LogMsg "Getting the first key $firstkey"
			secondkey=$(cat /sys/class/infiniband/mlx5_0/ports/1/pkeys/1)
			LogMsg "Getting the second key $secondkey"

			# Assign the bigger number to MPI_IB_PKEY
			if [ $((firstkey - secondkey)) -gt 0 ]; then
				export MPI_IB_PKEY=$firstkey
				echo "MPI_IB_PKEY=$firstkey" >> /root/constants.sh
			else
				export MPI_IB_PKEY=$secondkey
				echo "MPI_IB_PKEY=$secondkey" >> /root/constants.sh
			fi
			LogMsg "Setting MPI_IB_PKEY to $MPI_IB_PKEY and copying it into constants.sh file"
		else
			LogMsg "pkey is already present in constants.sh"
		fi
	else
		LogMsg "Skipped MPI_IB_PKEY query step in ND device"
	fi

	for vm in $master $slaves_array; do
		LogMsg "Checking $ib_nic status in $vm"
		# Verify ib_nic exists or not.
		ssh root@${vm} "ip addr show $ib_nic | grep 'inet '" > /dev/null
		ib_nic_status=$?
		ssh root@${vm} "ip addr show $ib_nic > $ib_nic-status-${vm}.txt"
		scp root@${vm}:${ib_nic}-status-${vm}.txt .
		if [ $ib_nic_status -eq 0 ]; then
			# Verify ib_nic has IP address, which means IB setup is ready
			LogMsg "${ib_nic} IP detected for ${vm}."
		else
			# Verify no IP address on ib_nic, which means IB setup is not ready
			LogErr "${ib_nic} failed to get IP address for ${vm}."
			err_virtual_machines=$(($err_virtual_machines+1))
		fi
		final_ib_nic_status=$(($final_ib_nic_status + $ib_nic_status))
		total_virtual_machines=$(($total_virtual_machines + 1))
	done

	if [ $final_ib_nic_status -ne 0 ]; then
		LogErr "$err_virtual_machines VMs out of $total_virtual_machines did get IP address for $ib_nic. Aborting Tests"
		SetTestStateFailed
		Collect_Logs
		LogErr "INFINIBAND_VERIFICATION_FAILED_${ib_nic}"
		exit 0
	else
		# Verify all VM have ib_nic available for further testing
		LogMsg "INFINIBAND_VERIFICATION_SUCCESS_${ib_nic}"
		# Removing controller VM from total_virtual_machines count
		total_virtual_machines=$(($total_virtual_machines - 1))
	fi

	# ############################################################################################################
	# ib kernel modules verification
	# mlx5_ib, rdma_cm, rdma_ucm, ib_ipoib, ib_umad shall be loaded in kernel
	final_module_load_status=0
	if [[ $is_nd == "yes" ]]; then
		kernel_modules="rdma_cm rdma_ucm ib_ipoib ib_umad"
	else
		kernel_modules="mlx5_ib rdma_cm rdma_ucm ib_ipoib ib_umad"
	fi

	for vm in $master $slaves_array; do
	LogMsg "Checking kernel modules in $vm"
		for k_mod in $kernel_modules; do
			ssh root@${vm} "lsmod | grep ${k_mod}" > /dev/null
			k_mod_status=$?
			if [ $k_mod_status -eq 0 ]; then
				# Verify ib kernel module is loaded in the system
				LogMsg "${k_mod} module is loaded in ${vm}."
			else
				# Verify ib kernel module is not loaded in the system
				LogErr "${k_mod} module is not loaded in ${vm}."
				err_virtual_machines=$(($err_virtual_machines+1))
			fi
			final_module_load_status=$(($final_module_load_status + $k_mod_status))
		done
	done

	# ############################################################################################################
	# ibv_devinfo verifies PORT STATE
	# PORT_ACTIVE (4) is expected. If PORT_DOWN (1), it fails
	# wait 5-second for port establishment
	if [[ $is_nd == "yes" ]]; then
		# ND device loading takes time.
		LogMsg "Waiting 60 seconds for ND interface load"
		sleep 60
	fi
	ib_port_state_down_cnt=0
	min_port_state_up_cnt=0
	for vm in $master $slaves_array; do
		min_port_state_up_cnt=$(($min_port_state_up_cnt + 1))
		ssh root@${vm} "ibv_devinfo > /root/IMB-PORT_STATE_${vm}.txt"
		port_state=$(ssh root@${vm} "ibv_devinfo | grep -i state")
		if [[ "$port_state" == *"PORT_ACTIVE"* ]]; then
			LogMsg "$vm ib port is up - Succeeded; $port_state"
		else
			LogErr "$vm ib port is down; $port_state"
			LogErr "Will remove the VM with bad port from constants.sh"
			sed -i "s/${vm},\|,${vm}//g" ${__LIS_CONSTANTS_FILE}
			ib_port_state_down_cnt=$(($ib_port_state_down_cnt + 1))
		fi
	done
	min_port_state_up_cnt=$((min_port_state_up_cnt / 2))
	# If half of the VMs (or more) are affected, the test will fail
	if [ $ib_port_state_down_cnt -ge $min_port_state_up_cnt ]; then
		LogErr "IMB-MPI1 ib port state check failed in $ib_port_state_down_cnt VMs. Aborting further tests."
		SetTestStateFailed
		Collect_Logs
		LogMsg "INFINIBAND_VERIFICATION_FAILED_MPI1_PORTSTATE"
		exit 0
	else
		LogMsg "INFINIBAND_VERIFICATION_SUCCESS_MPI1_PORTSTATE"
	fi
	# Refresh slave array and total_virtual_machines
	if [ $ib_port_state_down_cnt -gt 0 ]; then
		. ${__LIS_CONSTANTS_FILE}
		slaves_array=$(echo ${slaves} | tr ',' ' ')
		total_virtual_machines=$(($total_virtual_machines - $ib_port_state_down_cnt))
		ib_port_state_down_cnt=0
	fi

	# ############################################################################################################
	# Verify if SetupRDMA completed all steps or not
	# IF completed successfully, constants.sh has setup_completed=0
	setup_state_cnt=0
	for vm in $master $slaves_array; do
		setup_result=$(ssh root@${vm} "cat /root/constants.sh | grep -i setup_completed" | head -1)
		setup_result=$(echo $setup_result | cut -d '=' -f 2)
		if [ "$setup_result" == "0" ]; then
			LogMsg "$vm RDMA setup - Succeeded; $setup_result"
		else
			LogErr "$vm RDMA setup - Failed; $setup_result"
			setup_state_cnt=$(($setup_state_cnt + 1))
		fi
	done

	if [ $setup_state_cnt -ne 0 ]; then
		LogErr "IMB-MPI1 SetupRDMA state check failed in $setup_state_cnt VMs. Aborting further tests."
		SetTestStateFailed
		Collect_Logs
		LogMsg "INFINIBAND_VERIFICATION_FAILED_MPI1_SETUPSTATE"
		exit 0
	else
		LogMsg "INFINIBAND_VERIFICATION_SUCCESS_MPI1_SETUPSTATE"
	fi

	# ############################################################################################################
	# Remove bad node from the testing. There is known issue about Limit_UAR issue in mellanox driver.
	# Scanning dmesg to find ALLOC_UAR, and remove those bad node out of $slaves_array
	alloc_uar_limited_cnt=0

	echo $slaves_array > /root/tmp_slaves_array.txt
	for vm in $slaves_array; do
		ssh root@$i 'dmesg | grep ALLOC_UAR' > /dev/null 2>&1;
		if [ "$?" == "0" ]; then
			LogErr "$vm RDMA state reach to limit of ALLOC_UAR - Failed and removed from target slaves."
			sed -i 's/$vm//g' /root/tmp_slaves_array.txt
			alloc_uar_limited_cnt=$(($alloc_uar_limited_cnt + 1))
		else
			LogMsg "$vm RDMA state verified healthy - Succeeded."
		fi
	done
	# Refresh $slaves_array with healthy node
	slaves_array=$(cat /root/tmp_slaves_array.txt)

	# ############################################################################################################
	# Verify ibv_rc_pingpong, ibv_uc_pingpong and ibv_ud_pingpong and rping.
	final_pingpong_state=0
	found_ib0_interface=1

	if [[ $is_nd == "no" ]]; then
		# Getting ib0 interface address and store in constants.sh
		slaves_array=$(echo ${slaves} | tr ',' ' ')
		ib_name=ib0
		for vm in $master $slaves_array; do
			ib0=$(ssh root@${vm} ip addr show $ib_name | awk -F ' *|:' '/inet /{print $3}' | cut -d / -f 1)
			if [[ $? -eq 0 && $ib0 ]]; then
				LogMsg "Successfully queried $ib_name interface address, $ib0 from ${vm}."
			else
				LogErr "Failed to query $ib_name interface address, $ib0 from ${vm}."
				final_pingpong_state=$(($final_pingpong_state + 1))
				found_ib0_interface=0
			fi
			LogMsg "Logging ib0_$vm value: $ib0"
			vm_id=$(echo $vm | sed -r 's!/.*!!; s!.*\.!!')
			echo ib0_$vm_id=$ib0 >> /root/constants.sh
			export ib0_$vm_id=$ib0
		done

		# Define ibv_ pingpong commands in the array
		declare -a ping_cmds=("ibv_rc_pingpong" "ibv_uc_pingpong" "ibv_ud_pingpong")

		if [ $found_ib0_interface = 1 ]; then
			for ping_cmd in "${ping_cmds[@]}"; do
				for vm1 in $master $slaves_array; do
					for vm2 in $slaves_array $master; do
						if [[ "$vm1" == "$vm2" ]]; then
							# Skip self-ping test case
							break
						fi
						# Define pingpong test log file name
						log_file=IMB-"$ping_cmd"-output-$vm1-$vm2.txt
						LogMsg "Run $ping_cmd from $vm2 to $vm1"
						LogMsg "  Start $ping_cmd in server VM $vm1 first"
						retries=0
						while [ $retries -lt 3 ]; do
							ssh root@${vm1} "$ping_cmd" &
							LogMsg "  $?"
							sleep 1
							vm1_id=ib0_$(echo $vm1 | sed -r 's!/.*!!; s!.*\.!!')
							LogMsg "  Start $ping_cmd in client VM, $vm2 to ${!vm1_id}"
							ssh root@${vm2} "$ping_cmd ${!vm1_id} > /root/$log_file"
							pingpong_state=$?
							LogMsg "  $pingpong_state"

							sleep 1
							scp root@${vm2}:/root/$log_file .
							pingpong_result=$(cat $log_file | grep -i Mbit | cut -d ' ' -f7)
							if [ $pingpong_state -eq 0 ] && [ $pingpong_result > 0 ]; then
								LogMsg "$ping_cmd test execution successful"
								LogMsg "$ping_cmd result $pingpong_result in $vm1-$vm2 - Succeeded."
								retries=4
							else
								sleep 10
								let retries=retries+1
							fi
						done
						if [ $pingpong_state -ne 0 ] || (($(echo "$pingpong_result <= 0" | bc -l))); then
							LogErr "$ping_cmd test execution failed"
							LogErr "$ping_cmd result $pingpong_result in $vm1-$vm2 - Failed"
							final_pingpong_state=$(($final_pingpong_state + 1))
						fi
					done
				done
			done
		fi

		if [ $final_pingpong_state -ne 0 ]; then
			LogErr "ibv_ping_pong test failed in some VMs. Aborting further tests."
			SetTestStateFailed
			Collect_Logs
			LogErr "INFINIBAND_VERIFICATION_FAILED_IBV_PINGPONG"
			exit 0
		else
			LogMsg "INFINIBAND_VERIFICATION_SUCCESS_IBV_PINGPONG"
		fi
	else
		LogMsg "ND test skipped ibv_ping_pong test"
	fi

	non_shm_mpi_settings=$(echo $mpi_settings | sed 's/shm://')
	imb_ping_pong_path=$(find / -name ping_pong)
	imb_mpi1_path=$(find / -name IMB-MPI1 | head -n 1)
	imb_rma_path=$(find / -name IMB-RMA | head -n 1)
	imb_nbc_path=$(find / -name IMB-NBC | head -n 1)
	imb_p2p_path=$(find / -name IMB-P2P | head -n 1)
	imb_io_path=$(find / -name IMB-IO | head -n 1)
	omb_path=$(find / -name osu-micro-benchmarks | tail -n 1)

	case "$mpi_type" in
		ibm)
			modified_slaves=${slaves//,/:$VM_Size,}
			mpi_run_path=$(find / -name mpirun | grep -i ibm | grep -v ia)
		;;
		open)
			total_virtual_machines=$(($total_virtual_machines + 1))
			mpi_run_path=$(whereis mpirun | awk -v FS=' ' '{print $2}')
		;;
		hpcx)
			total_virtual_machines=$(($total_virtual_machines + 1))
			mpi_run_path=$(find / -name mpirun | head -n 1)
			export UCX_IB_PKEY=$(printf '0x%04x' "$(( $MPI_IB_PKEY & 0x0FFF ))")
			hpcx_init=$(find / -name hpcx-init.sh | grep root)
			source $hpcx_init; hpcx_load
		;;
		intel)
			vars=$(find / -name mpivars.sh | grep intel)
			source $vars
			imb_mpi1_path=$(find / -name IMB-MPI1 | grep intel)
			imb_rma_path=$(find / -name IMB-RMA | grep intel)
			imb_nbc_path=$(find / -name IMB-NBC | grep intel)
			mpi_run_path=$(find / -name mpirun | grep intel64)
		;;
		mvapich)
			omb_path=$(find / -name osu_benchmarks | tail -n 1)
			total_virtual_machines=$(($total_virtual_machines + 1))
			mpi_run_path=$(find / -name mpirun_rsh | tail -n 1)
		;;
		*)
			LogErr "MPI not supported"
			SetTestStateFailed
			exit 0
		;;
	esac
	LogMsg "MPIRUN Path: $mpi_run_path"
	LogMsg "IMB-MPI1 Path: $imb_mpi1_path"
	LogMsg "IMB-RMA Path: $imb_rma_path"
	LogMsg "IMB-NBC Path: $imb_nbc_path"
	LogMsg "IMB-P2P Path: $imb_p2p_path"
	LogMsg "IMB-IO Path: $imb_io_path"
	LogMsg "OMB Path: $omb_path"

	# Run all benchmarks
	if [[ $benchmark_type == "OMB" ]]; then
		LogMsg "Running OMB benchmarks tests for $mpi_type"
		Run_OMB_P2P
	elif [[ $benchmark_type == "IMB" ]]; then
		LogMsg "Running IMB benchmarks tests for $mpi_type"
		Run_IMB_Intranode
		Run_IMB_MPI1
		if [[ $quicktestonly == "no" ]]; then
			Run_IMB_RMA
			Run_IMB_NBC
			# Sometimes IMB-P2P and IMB-IO aren't available, skip them if it's the case
			if [ ! -z "$imb_p2p_path" ]; then
				Run_IMB_P2P
			else
				LogMsg "INFINIBAND_VERIFICATION_SKIPPED_IMB_P2P_ALLNODES"
			fi
			if [ ! -z "$imb_io_path" ]; then
				Run_IMB_IO
			else
				LogMsg "INFINIBAND_VERIFICATION_SKIPPED_IMB_IO_ALLNODES"
			fi
		else
			LogMsg "INFINIBAND_VERIFICATION_SKIPPED_IMB_RMA_ALLNODES"
			LogMsg "INFINIBAND_VERIFICATION_SKIPPED_IMB_NBC_ALLNODES"
			LogMsg "INFINIBAND_VERIFICATION_SKIPPED_IMB_P2P_ALLNODES"
			LogMsg "INFINIBAND_VERIFICATION_SKIPPED_IMB_IO_ALLNODES"
		fi
	fi

	# Get all results and finish the test
	Collect_Logs
	finalStatus=$(($final_ib_nic_status + $ib_port_state_down_cnt + $alloc_uar_limited_cnt + $final_mpi_intranode_status + $imb_mpi1_final_status + $imb_nbc_final_status + $omb_p2p_final_status))
	if [ $finalStatus -ne 0 ]; then
		LogMsg "${ib_nic}_status: $final_ib_nic_status"
		LogMsg "ib_port_state_down_cnt: $ib_port_state_down_cnt"
		LogMsg "alloc_uar_limited_cnt: $alloc_uar_limited_cnt"
		LogMsg "final_mpi_intranode_status: $final_mpi_intranode_status"
		LogMsg "imb_mpi1_final_status: $imb_mpi1_final_status"
		LogMsg "imb_rma_final_status: $imb_rma_final_status"
		LogMsg "imb_nbc_final_status: $imb_nbc_final_status"
		LogMsg "imb_p2p_final_status: $imb_p2p_final_status"
		LogMsg "imb_io_final_status: $imb_io_final_status"
		LogMsg "omb_p2p_final_status: $omb_p2p_final_status"
		LogErr "INFINIBAND_VERIFICATION_FAILED"
		SetTestStateFailed
	else
		LogMsg "INFINIBAND_VERIFIED_SUCCESSFULLY"
		SetTestStateCompleted
	fi
	exit 0
}

Main