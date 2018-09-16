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
	echo "TestAborted" >state.txt
	exit 0
}

# Source constants file and initialize most common variables
UtilsInit

HOMEDIR="/root"
#
# Constants/Globals
#
CONSTANTS_FILE="/root/constants.sh"

imb_mpi1_final_status=0
imb_rma_final_status=0
imb_nbc_final_status=0

#Get all the Kernel-Logs from all VMs.
collect_kernel_logs_from_all_vms() {
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
}

compress_files() {
	compressed_file_name=$1
	pattern=$2
	LogMsg "Compressing ${pattern} files into ${compressed_file_name}"
	tar -cvzf temp-${compressed_file_name} ${pattern}*
	if [ $? -eq 0 ]; then
		mv temp-${compressed_file_name} ${compressed_file_name}
		LogMsg "${pattern}* files compresssed successfully."
		LogMsg "Deleting local copies of ${pattern}* files"
		rm -rvf ${pattern}*
	else
		LogErr "Failed to compress files."
		LogMsg "Don't worry. Your files are still here."
	fi
}

if [ -e ${CONSTANTS_FILE} ]; then
	source ${CONSTANTS_FILE}
else
	error_message="missing ${CONSTANTS_FILE} file"
	LogErr "${error_message}"
	SetTestStateFailed
	exit 1
fi

slaves_array=$(echo ${slaves} | tr ',' ' ')
mpi_run_path=$(find / -name mpirun | grep intel64)
LogMsg "MPIRUN Path: $mpi_run_path"
imb_mpi1_path=$(find / -name IMB-MPI1 | grep intel64)
LogMsg "IMB-MPI1 Path: $imb_mpi1_path"
imb_rma_path=$(find / -name IMB-RMA | grep intel64)
LogMsg "IMB-RMA Path: $imb_rma_path"
imb_nbc_path=$(find / -name IMB-NBC | grep intel64)
LogMsg "IMB-NBC Path: $imb_nbc_path"

#Verify if ib_nic got IP address on All VMs in current cluster.
final_ib_nic_status=0
total_virtual_machines=0
slaves_array=$(echo ${slaves} | tr ',' ' ')
for vm in $master $slaves_array; do
	LogMsg "Checking $ib_nic status in $vm"
	temp=$(ssh root@${vm} "ifconfig $ib_nic | grep 'inet '")
	ib_nic_status=$?
	ssh root@${vm} "ifconfig $ib_nic > $ib_nic-status-${vm}.txt"
	scp root@${vm}:${ib_nic}-status-${vm}.txt .
	if [ $ib_nic_status -eq 0 ]; then
		LogMsg "${ib_nic} IP detected for ${vm}."
	else
		LogErr "${ib_nic} failed to get IP address for ${vm}."
	fi
	final_ib_nic_status=$(($final_ib_nic_status + $ib_nic_status))
	total_virtual_machines=$(($total_virtual_machines + 1))
done
if [ $final_ib_nic_status -ne 0 ]; then
	LogErr "Some VMs did get IP address for $ib_nic. Aborting Tests"
	SetTestStateFailed
	collect_kernel_logs_from_all_vms
	LogErr "INFINIBAND_VERIFICATION_FAILED_${ib_nic}"
	exit 0
else
	LogMsg "INFINIBAND_VERIFICATION_SUCCESS_${ib_nic}"
fi

##Verify MPI Tests
non_shm_mpi_settings=$(echo $mpi_settings | sed 's/shm://')

#Verify PingPong Tests (IntraNode).
final_mpi_intranode_status=0
slaves_array=$(echo ${slaves} | tr ',' ' ')

for vm in $master $slaves_array; do
	LogMsg "$mpi_run_path -hosts $vm -ppn 2 -n 2 $non_shm_mpi_settings $imb_mpi1_path pingpong"
	LogMsg "Checking IMB-MPI1 Intranode status in $vm"
	ssh root@${vm} "$mpi_run_path -hosts $vm -ppn 2 -n 2 $non_shm_mpi_settings $imb_mpi1_path pingpong \
    > IMB-MPI1-IntraNode-pingpong-output-$vm.txt"
	mpi_intranode_status=$?
	scp root@${vm}:IMB-MPI1-IntraNode-pingpong-output-$vm.txt .
	if [ $mpi_intranode_status -eq 0 ]; then
		LogMsg "IMB-MPI1 Intranode status in $vm - Succeeded."
	else
		LogErr "IMB-MPI1 Intranode status in $vm - Failed"
	fi
	final_mpi_intranode_status=$(($final_mpi_intranode_status + $mpi_intranode_status))
done

if [ $final_mpi_intranode_status -ne 0 ]; then
	LogErr "IMB-MPI1 Intranode test failed in somes VMs. Aborting further tests."
	SetTestStateFailed
	collect_kernel_logs_from_all_vms
	LogMsg "INFINIBAND_VERIFICATION_FAILED_MPI1_INTRANODE"
	exit 0
else
	LogErr "INFINIBAND_VERIFICATION_SUCCESS_MPI1_INTRANODE"
fi

#Verify PingPong Tests (InterNode).
final_mpi_internode_status=0
slaves_array=$(echo ${slaves} | tr ',' ' ')
for vm in $slaves_array; do
	LogMsg "$mpi_run_path -hosts $master,$vm -ppn 1 -n 2 $non_shm_mpi_settings $imb_mpi1_path pingpong"
	LogMsg "Checking IMB-MPI1 InterNode status in $vm"
	$mpi_run_path -hosts $master,$vm -ppn 1 -n 2 $non_shm_mpi_settings $imb_mpi1_path pingpong \
		>IMB-MPI1-InterNode-pingpong-output-${master}-${vm}.txt
	mpi_internode_status=$?
	if [ $mpi_internode_status -eq 0 ]; then
		LogMsg "IMB-MPI1 Internode status in $vm - Succeeded."
	else
		LogErr "IMB-MPI1 Internode status in $vm - Failed"
	fi
	final_mpi_internode_status=$(($final_mpi_internode_status + $mpi_internode_status))
done

if [ $final_mpi_internode_status -ne 0 ]; then
	LogErr "IMB-MPI1 Internode test failed in somes VMs. Aborting further tests."
	SetTestStateFailed
	collect_kernel_logs_from_all_vms
	LogErr "INFINIBAND_VERIFICATION_FAILED_MPI1_INTERNODE"
	exit 0
else
	LogMsg "INFINIBAND_VERIFICATION_SUCCESS_MPI1_INTERNODE"
fi

#Verify IMB-MPI1 (pingpong & allreduce etc) tests.
total_attempts=$(seq 1 1 $imb_mpi1_tests_iterations)
imb_mpi1_final_status=0
for attempt in $total_attempts; do
	if [[ $imb_mpi1_tests == "all" ]]; then
		LogMsg "$mpi_run_path -hosts $master,$slaves -ppn $mpi1_ppn -n \
        $(($mpi1_ppn * $total_virtual_machines)) $mpi_settings $imb_mpi1_path"
		LogMsg "IMB-MPI1 test iteration $attempt - Running."
		$mpi_run_path -hosts $master,$slaves -ppn $mpi1_ppn -n $(($mpi1_ppn * $total_virtual_machines))
		$mpi_settings $imb_mpi1_path >IMB-MPI1-AllNodes-output-Attempt-${attempt}.txt
		mpi_status=$?
	else
		LogMsg "$mpi_run_path -hosts $master,$slaves -ppn $mpi1_ppn -n \
        $(($mpi1_ppn * $total_virtual_machines)) $mpi_settings $imb_mpi1_path $imb_mpi1_tests"
		LogMsg "IMB-MPI1 test iteration $attempt - Running."
		$mpi_run_path -hosts $master,$slaves -ppn $mpi1_ppn -n \
			$(($mpi1_ppn * $total_virtual_machines)) $mpi_settings $imb_mpi1_path $imb_mpi1_tests \
			>IMB-MPI1-AllNodes-output-Attempt-${attempt}.txt
		mpi_status=$?
	fi
	if [ $mpi_status -eq 0 ]; then
		LogMsg "IMB-MPI1 test iteration $attempt - Succeeded."
		sleep 1
	else
		LogErr "IMB-MPI1 test iteration $attempt - Failed."
		imb_mpi1_final_status=$(($imb_mpi1_final_status + $mpi_status))
		sleep 1
	fi
done

if [ $imb_mpi1_tests_iterations -gt 5 ]; then
	compress_files "IMB-MPI1-AllNodes-output.tar.gz" "IMB-MPI1-AllNodes-output-Attempt"
fi

if [ $imb_mpi1_final_status -ne 0 ]; then
	LogErr "IMB-MPI1 tests returned non-zero exit code."
	SetTestStateFailed
	collect_kernel_logs_from_all_vms
	LogErr "INFINIBAND_VERIFICATION_FAILED_MPI1_ALLNODES"
	exit 0
else
	LogMsg "INFINIBAND_VERIFICATION_SUCCESS_MPI1_ALLNODES"

fi

#Verify IMB-RMA tests.
total_attempts=$(seq 1 1 $imb_rma_tests_iterations)
imb_rma_final_status=0
for attempt in $total_attempts; do
	if [[ $imb_rma_tests == "all" ]]; then
		LogMsg "$mpi_run_path -hosts $master,$slaves -ppn $rma_ppn -n \
        $(($rma_ppn * $total_virtual_machines)) $mpi_settings $imb_rma_path"
		LogMsg "IMB-RMA test iteration $attempt - Running."
		$mpi_run_path -hosts $master,$slaves -ppn $rma_ppn -n \
			$(($rma_ppn * $total_virtual_machines)) $mpi_settings $imb_rma_path \
			>IMB-RMA-AllNodes-output-Attempt-${attempt}.txt
		rma_status=$?
	else
		LogMsg "$mpi_run_path -hosts $master,$slaves -ppn $rma_ppn -n \
        $(($rma_ppn * $total_virtual_machines)) $mpi_settings $imb_rma_path $imb_rma_tests"
		LogMsg "IMB-RMA test iteration $attempt - Running."
		$mpi_run_path -hosts $master,$slaves -ppn $rma_ppn -n \
			$(($rma_ppn * $total_virtual_machines)) $mpi_settings $imb_rma_path $imb_rma_tests \
			>IMB-RMA-AllNodes-output-Attempt-${attempt}.txt
		rma_status=$?
	fi
	if [ $rma_status -eq 0 ]; then
		LogMsg "IMB-RMA test iteration $attempt - Succeeded."
		sleep 1
	else
		LogErr "IMB-RMA test iteration $attempt - Failed."
		imb_rma_final_status=$(($imb_rma_final_status + $rma_status))
		sleep 1
	fi
done

if [ $imb_rma_tests_iterations -gt 5 ]; then
	compress_files "IMB-RMA-AllNodes-output.tar.gz" "IMB-RMA-AllNodes-output-Attempt"
fi

if [ $imb_rma_final_status -ne 0 ]; then
	LogErr "IMB-RMA tests returned non-zero exit code. Aborting further tests."
	SetTestStateFailed
	collect_kernel_logs_from_all_vms
	LogErr "INFINIBAND_VERIFICATION_FAILED_RMA_ALLNODES"
	exit 0
else
	LogMsg "INFINIBAND_VERIFICATION_SUCCESS_RMA_ALLNODES"
fi

#Verify IMB-NBC tests.
total_attempts=$(seq 1 1 $imb_nbc_tests_iterations)
imb_nbc_final_status=0
for attempt in $total_attempts; do
	if [[ $imb_nbc_tests == "all" ]]; then
		LogMsg "$mpi_run_path -hosts $master,$slaves -ppn $nbc_ppn -n \
        $(($nbc_ppn * $total_virtual_machines)) $mpi_settings $imb_nbc_path"
		LogMsg "IMB-NBC test iteration $attempt - Running."
		$mpi_run_path -hosts $master,$slaves -ppn $nbc_ppn -n \
			$(($nbc_ppn * $total_virtual_machines)) $mpi_settings $imb_nbc_path \
			>IMB-NBC-AllNodes-output-Attempt-${attempt}.txt
		nbc_status=$?
	else
		LogMsg "$mpi_run_path -hosts $master,$slaves -ppn $nbc_ppn -n $(($nbc_ppn * $total_virtual_machines)) $mpi_settings $imb_nbc_path $imb_nbc_tests"
		LogMsg "IMB-NBC test iteration $attempt - Running."
		$mpi_run_path -hosts $master,$slaves -ppn $nbc_ppn -n $(($nbc_ppn * $total_virtual_machines)) $mpi_settings $imb_nbc_path $imb_nbc_tests >IMB-NBC-AllNodes-output-Attempt-${attempt}.txt
		nbc_status=$?
	fi
	if [ $nbc_status -eq 0 ]; then
		LogMsg "IMB-NBC test iteration $attempt - Succeeded."
		sleep 1
	else
		LogErr "IMB-NBC test iteration $attempt - Failed."
		imb_nbc_final_status=$(($imb_nbc_final_status + $nbc_status))
		sleep 1
	fi
done

if [ $imb_rma_tests_iterations -gt 5 ]; then
	mpi_status "IMB-NBC-AllNodes-output.tar.gz" "IMB-NBC-AllNodes-output-Attempt"
fi

if [ $imb_nbc_final_status -ne 0 ]; then
	LogErr "IMB-RMA tests returned non-zero exit code. Aborting further tests."
	SetTestStateFailed
	collect_kernel_logs_from_all_vms
	LogErr "INFINIBAND_VERIFICATION_FAILED_NBC_ALLNODES"
	exit 0
else
	LogMsg "INFINIBAND_VERIFICATION_SUCCESS_NBC_ALLNODES"
fi

collect_kernel_logs_from_all_vms

finalStatus=$(($ib_nic_status + $final_mpi_intranode_status + $final_mpi_internode_status + $imb_mpi1_final_status + $imb_rma_final_status + $imb_nbc_final_status))

if [ $finalStatus -ne 0 ]; then
	LogMsg "${ib_nic}_status: $ib_nic_status"
	LogMsg "final_mpi_intranode_status: $final_mpi_intranode_status"
	LogMsg "final_mpi_internode_status: $final_mpi_internode_status"
	LogMsg "imb_mpi1_final_status: $imb_mpi1_final_status"
	LogMsg "imb_rma_final_status: $imb_rma_final_status"
	LogMsg "imb_nbc_final_status: $imb_nbc_final_status"
	LogErr "INFINIBAND_VERIFICATION_FAILED"
	SetTestStateFailed
else
	LogMsg "INFINIBAND_VERIFIED_SUCCESSFULLY"
	SetTestStateCompleted
fi

#It is important to exit with zero. Otherwise, Autmatinon will try to run the scrtipt again.
#Result analysis is already done in the script with be checked by automation as well.
exit 0
