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

imb_mpi1_final_status=0
imb_rma_final_status=0
imb_nbc_final_status=0

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
        LogErr "INFINIBAND_VERIFICATION_FAILED_MPI1_INTRANODE"
        exit 0
    else
        LogMsg "INFINIBAND_VERIFICATION_SUCCESS_MPI1_INTRANODE"
    fi
}

function Run_IMB_MPI1() {
    total_attempts=$(seq 1 1 $imb_mpi1_tests_iterations)
    imb_mpi1_final_status=0
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
            intel)
                LogMsg "$mpi_run_path -hosts $master,$modified_slaves -ppn $mpi1_ppn -n $(($VM_Size * $total_virtual_machines)) $mpi_settings $extra_params"
                $mpi_run_path -hosts $master,$modified_slaves -ppn $mpi1_ppn -n $(($VM_Size * $total_virtual_machines)) $mpi_settings $imb_mpi1_path $extra_params > IMB-MPI1-AllNodes-output-Attempt-${attempt}.txt
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
        LogErr "INFINIBAND_VERIFICATION_FAILED_MPI1_ALLNODES"
        exit 0
    else
        LogMsg "INFINIBAND_VERIFICATION_SUCCESS_MPI1_ALLNODES"
    fi
}

function Run_IMB_RMA() {
    total_attempts=$(seq 1 1 $imb_rma_tests_iterations)
    imb_rma_final_status=0
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
            intel)
                LogMsg "$mpi_run_path -hosts $master,$modified_slaves -ppn $mpi1_ppn -n $(($VM_Size * $total_virtual_machines)) $mpi_settings $imb_rma_path $extra_params"
                $mpi_run_path -hosts $master,$modified_slaves -ppn $mpi1_ppn -n $(($VM_Size * $total_virtual_machines)) $mpi_settings $imb_rma_path $extra_params > IMB-RMA-AllNodes-output-Attempt-${attempt}.txt
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
        LogErr "INFINIBAND_VERIFICATION_FAILED_RMA_ALLNODES"
        exit 0
    else
        LogMsg "INFINIBAND_VERIFICATION_SUCCESS_RMA_ALLNODES"
    fi
}

function Run_IMB_NBC() {
    total_attempts=$(seq 1 1 $imb_nbc_tests_iterations)
    imb_nbc_final_status=0
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
                intel)
                    LogMsg "$mpi_run_path -hosts $master,$modified_slaves -ppn $nbc_ppn -n $(($VM_Size * $total_virtual_machines)) $mpi_settings $imb_nbc_path $extra_params"
                    $mpi_run_path -hosts $master,$modified_slaves -ppn $nbc_ppn -n $(($VM_Size * $total_virtual_machines)) $mpi_settings $imb_nbc_path $extra_params > IMB-NBC-AllNodes-output-Attempt-${attempt}.txt
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
        LogErr "INFINIBAND_VERIFICATION_FAILED_NBC_ALLNODES"
        exit 0
    else
        LogMsg "INFINIBAND_VERIFICATION_SUCCESS_NBC_ALLNODES"
    fi
}

function Main() {
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

    for vm in $master $slaves_array; do
        LogMsg "Checking $ib_nic status in $vm"
        # Verify ib_nic exists or not.
        ssh root@${vm} "ifconfig $ib_nic | grep 'inet '" > /dev/null
        ib_nic_status=$?
        ssh root@${vm} "ifconfig $ib_nic > $ib_nic-status-${vm}.txt"
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
    # mlx5_ib, rdma_cm, rdma_ucm, ib_ipoib shall be loaded in kernel
    final_module_load_status=0
    kernel_modules="mlx5_ib rdma_cm rdma_ucm ib_ipoib"

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

    if [ $final_module_load_status -ne 0 ]; then
        LogErr "$err_virtual_machines VMs out of $total_virtual_machines did not load kernel modules successfully. Aborting Tests"
        SetTestStateFailed
        Collect_Logs
        LogErr "INFINIBAND_VERIFICATION_FAILED_${kernel_modules}"
        exit 0
    else
        # Verify all VM have ib_nic available for further testing
        LogMsg "INFINIBAND_VERIFICATION_SUCCESS_${kernel_modules}"
    fi

    # ############################################################################################################
    # ibv_devinfo verifies PORT STATE
    # PORT_ACTIVE (4) is expected. If PORT_DOWN (1), it fails
    ib_port_state_down_cnt=0
    min_port_state_up_cnt=0
    for vm in $master $slaves_array; do
        min_port_state_up_cnt=$(($min_port_state_up_cnt + 1))
        ssh root@${vm} "ibv_devinfo > /root/IMB-PORT_STATE_${vm}.txt"
        port_state=$(ssh root@${vm} "ibv_devinfo | grep -i state")
        port_state=$(echo $port_state | cut -d ' ' -f2)
        if [ "$port_state" == "PORT_ACTIVE" ]; then
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
        setup_result=$(ssh root@${vm} "cat /root/constants.sh | grep -i setup_completed")
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

    # Define ibv_ pingpong commands in the array
    declare -a ping_cmds=("ibv_rc_pingpong" "ibv_uc_pingpong" "ibv_ud_pingpong")

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
                    sleep 1
                    LogMsg "  Start $ping_cmd in client VM $vm2"
                    ssh root@${vm2} "$ping_cmd $vm1 > /root/$log_file"
                    pingpong_state=$?

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

    if [ $final_pingpong_state -ne 0 ]; then
        LogErr "ibv_ping_pong test failed in some VMs. Aborting further tests."
        SetTestStateFailed
        Collect_Logs
        LogErr "INFINIBAND_VERIFICATION_FAILED_IBV_PINGPONG"
        exit 0
    else
        LogMsg "INFINIBAND_VERIFICATION_SUCCESS_IBV_PINGPONG"
    fi

    non_shm_mpi_settings=$(echo $mpi_settings | sed 's/shm://')
    imb_ping_pong_path=$(find / -name ping_pong)
    imb_mpi1_path=$(find / -name IMB-MPI1 | head -n 1)
    imb_rma_path=$(find / -name IMB-RMA | head -n 1)
    imb_nbc_path=$(find / -name IMB-NBC | head -n 1)
    case "$mpi_type" in
        ibm)
            modified_slaves=${slaves//,/:$VM_Size,}
            mpi_run_path=$(find / -name mpirun | grep -i ibm | grep -v ia)
        ;;
        open)
            total_virtual_machines=$(($total_virtual_machines + 1))
            mpi_run_path=$(find / -name mpirun | head -n 1)
        ;;
        intel)
            mpi_run_path=$(find / -name mpirun | grep intel64)
        ;;
        mvapich)
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

    # Run all benchmarks
    Run_IMB_Intranode
    Run_IMB_MPI1
    Run_IMB_RMA
    Run_IMB_NBC

    # Get all results and finish the test
    Collect_Logs
    finalStatus=$(($final_ib_nic_status + $ib_port_state_down_cnt + $alloc_uar_limited_cnt + $final_mpi_intranode_status + $imb_mpi1_final_status + $imb_nbc_final_status))
    if [ $finalStatus -ne 0 ]; then
        LogMsg "${ib_nic}_status: $final_ib_nic_status"
        LogMsg "ib_port_state_down_cnt: $ib_port_state_down_cnt"
        LogMsg "alloc_uar_limited_cnt: $alloc_uar_limited_cnt"
        LogMsg "final_mpi_intranode_status: $final_mpi_intranode_status"
        LogMsg "imb_mpi1_final_status: $imb_mpi1_final_status"
        LogMsg "imb_rma_final_status: $imb_rma_final_status"
        LogMsg "imb_nbc_final_status: $imb_nbc_final_status"
        LogErr "INFINIBAND_VERIFICATION_FAILED"
        SetTestStateFailed
    else
        LogMsg "INFINIBAND_VERIFIED_SUCCESSFULLY"
        SetTestStateCompleted
    fi
    exit 0
}

Main