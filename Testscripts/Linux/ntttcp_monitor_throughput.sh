#!/bin/bash
########################################################################
#
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
# In this script, we want to monitor the network throughput by ntttcp for running very long time, e.g. one month.
# Any throughput churn that's upper/lower than (${tolerance} * ${throughput_baseline}) will be logged as Failed (out of tolerance).
########################################################################

# Source utils.sh
. utils.sh || {
    echo "Error: unable to source utils.sh!"
    echo "TestAborted" > state.txt
    exit 0
}
# Source constants file and initialize most common variables
UtilsInit

function display_time_from_seconds {
    local T=$1
    local D=$((T/60/60/24))
    local H=$((T/60/60%24))
    local M=$((T/60%60))
    local S=$((T%60))
    (( $D > 0 )) && printf '%d days ' $D
    (( $H > 0 )) && printf '%d hours ' $H
    (( $M > 0 )) && printf '%d minutes ' $M
    (( $D > 0 || $H > 0 || $M > 0 )) && printf 'and '
    printf '%d seconds\n' $S
}

function main {
    while true;do
        case "$1" in
            --log_dir)
                log_dir="$2"
                shift 2;;
            --server_internal_ip)
                server_internal_ip="$2"
                shift 2;;
            --) shift; break ;;
            *) break ;;
        esac
    done

    if [[ -z ${seconds_of_runtime} || -z ${monitor_interval} || -z ${tolerance} || -z ${ntttcp_version} ]]; then
        LogMsg "Error: missing parameter 'seconds_of_runtime' or 'monitor_interval' or 'tolerance' or 'ntttcp_version' "
        exit 1
    elif (("${monitor_interval}" > 5)); then
        LogMsg "Warning: interval larger than 5 seconds may cause testing result not correct"
    fi

    if [[ -s state.txt ]]; then
        rm state.txt
    fi

    for ntttcp_pid in $(pidof ntttcp); do
        kill $ntttcp_pid
    done

    if [[ -d "${log_dir}" ]]; then
        rm -rf "${log_dir}"
    fi
    mkdir ${log_dir}
    if [[ -s "constants.sh" ]]; then
        cp -rf *.sh ${log_dir}
    fi

    update_repos
    install_package "gcc make wget moreutils bc"
    build_ntttcp ${ntttcp_version}

    # start testing depending on role (10.0.0.4 is receiver/server, other ip is sender/client)
    private_ip=$(hostname -I | awk '{print $1}')
    if [[ "${private_ip}" = "${server_internal_ip}" ]]; then
        nohup ntttcp -r -H &
        sleep 10
        SetTestStateRunning
        echo "Ntttcp_Monitor_Server_Started"
    else
        # 5 seconds for ntttcp starting and cooling down buffer
        end_time_readable=$(date -d "+$((${seconds_of_runtime} -5)) seconds" +"%Y-%m-%d %H:%M:%S")
        end_time=$(date -d "+$((${seconds_of_runtime} -5)) seconds" +%s)
        nohup ntttcp -s"${server_internal_ip}" -t ${seconds_of_runtime} | ts "%Y-%m-%d %H:%M:%S" > "${log_dir}"/monitor_ntttcp.log &
        # waiting for ntttcp process to start and get a stable throughput
        sleep $((${monitor_interval} + 10))

        # start monitoring on client
        while [ $end_time -gt $(date +%s) ]
        do
            date_back_interval=$(date -d "-${monitor_interval} seconds" +"%Y-%m-%d %H:%M:%S")
            # TODO: should we use tail, or direct use ./monitor_ntttcp.log? need more testing to select the most efficient
            # ntttcp log real-time throughput every 500ms, so interval
            tail -$((2 * ${monitor_interval} + 5)) "${log_dir}"/monitor_ntttcp.log > "${log_dir}"/tail_throughput.log
            sed -un '/'"${date_back_interval}"'/,$ s/.*/&/w '"${log_dir}"'/date_back_interval.log' "${log_dir}"/tail_throughput.log
            # if ./date_back_interval.log is empty, means ntttcp aborted due to networking device broken
            # exit and break from while loop
            if [[ ! -s "${log_dir}/date_back_interval.log" ]]; then
                break
            fi
            # also if "${log_dir}"/date_back_interval.log has some more columns that's not 'throughput|blank_space|unit' format
            # means networking device broken or ntttcp running down, exit and break from while loop
            # due to performance consideration, merge into above break for ./date_back_interval.log is empty
            sed -uni 's/.*Real-time\sthroughput:\s\([0-9.]*\)\(.*bps\)/\1 \2/p' "${log_dir}"/date_back_interval.log

            # average_throughput|blank_space|unit
            now_state=($(awk 'BEGIN{sum = 0} {sum += $1; now_unit = $2 } END{average = sum / NR; print average,now_unit}' "${log_dir}"/date_back_interval.log))

            if [[ (1 = $(echo "${now_state[0]} != 0" | bc)) && (-n "${now_state[1]}") ]]; then
                if [[ -z ${initialized} ]]; then
                    unit_baseline=${now_state[1]}
                    throughput_baseline=${now_state[0]}
                    throughput_max=${throughput_baseline}
                    throughput_min=${throughput_baseline}
                    threshold_upper=$(awk -v tol="${tolerance}" -v thr="${throughput_baseline}" "BEGIN {print (1 + tol) * thr}")
                    threshold_lower=$(awk -v tol="${tolerance}" -v thr="${throughput_baseline}" "BEGIN {print (1 - tol) * thr}")
                    initialized="initialized"
                elif [[ (1 = $(echo "${now_state[0]} > ${threshold_upper} ||  ${now_state[0]} < ${threshold_lower}" | bc)) || (${now_state[1]} != ${unit_baseline}) ]]; then
                    mv "${log_dir}"/date_back_interval.log "${log_dir}"/out_of_tolerance@${now_state[0]}_$(date +"%Y_%m_%d_%H_%M_%S")
                fi
                echo "TestRunning, EndTime: ${end_time_readable}, Baseline: ${throughput_baseline} ${unit_baseline},  Tolerance: +/- ${tolerance}, Now throughput: ${now_state[0]} ${now_state[1]}" > "${log_dir}"/state.txt
                if [[ 1 = $(echo "${now_state[0]} > ${throughput_max} && ${now_state[1]} == ${unit_baseline}" | bc) ]]; then
                    throughput_max=${now_state[0]}
                fi
                if [[ 1 = $(echo "${now_state[0]} < ${throughput_min} && ${now_state[1]} == ${unit_baseline}" | bc) ]]; then
                    throughput_min=${now_state[0]}
                fi
            fi
            # continue sleep interval even now_state (throughput) is under churn, until break the while for ./date_back_interval.log is empty
            sleep ${monitor_interval}
        done
        if [ $end_time -gt $(date +%s) ]; then
            LogMsg "Error: ntttcp aborted, which may be caused by network device error."
            echo "Error: ntttcp aborted, which may be caused by network device error." >> "${log_dir}"/out_of_tolerance@$(date +"%Y_%m_%d_%H_%M_%S")
        fi
        out_tolerance_logs=($(find "${log_dir}" -name 'out_of_tolerance@*'))
        if [[ ${#out_tolerance_logs[@]} -eq 0 ]]; then
            echo "TestCompleted" > "${log_dir}"/state.txt
            echo "Test Passed Successfully !" > "${log_dir}"/summary.log
            echo "Total Runtime: $(display_time_from_seconds ${seconds_of_runtime})" >> "${log_dir}"/summary.log
            echo "Monitor Interval: ${monitor_interval} seconds" >> "${log_dir}"/summary.log
            echo "Throughput Baseline: ${throughput_baseline} ${unit_baseline}" >> "${log_dir}"/summary.log
            echo "Tolerance: +/-${tolerance} of ${throughput_baseline} ${unit_baseline}" >> "${log_dir}"/summary.log
            echo "Maximum throughput: ${throughput_max}${unit_baseline}" >> "${log_dir}"/summary.log
            echo "Minimum throughput: ${throughput_min}${unit_baseline}" >> "${log_dir}"/summary.log
            echo "Real-time throughput consistently upper than ${threshold_lower} ${unit_baseline} and lower than ${threshold_upper} ${unit_baseline}" >> "${log_dir}"/summary.log
        else
            echo "TestFailed" > "${log_dir}"/state.txt
            echo "Test Passed Failed !" > "${log_dir}"/summary.log
            echo "Total Runtime: $(display_time_from_seconds ${seconds_of_runtime})" >> "${log_dir}"/summary.log
            echo "Monitor Interval: ${monitor_interval} seconds" >> "${log_dir}"/summary.log
            echo "Tolerance: +/-${tolerance} of ${throughput_baseline} ${unit_baseline}" >> "${log_dir}"/summary.log
            echo "Maximum throughput: ${throughput_max}${unit_baseline}" >> "${log_dir}"/summary.log
            echo "Minimum throughput: ${throughput_min}${unit_baseline}" >> "${log_dir}"/summary.log
            echo "Real-time throughput has ever been lower than ${threshold_lower} ${unit_baseline}, or upper than ${threshold_upper} ${unit_baseline}" >> "${log_dir}"/summary.log
            echo "Please reference TestExecutionError.txt"
            for log in "${out_tolerance_logs[@]}"; do
                echo "" >> "${log_dir}"/TestExecutionError.txt
                echo "$(basename $log)" | awk -F '@' '{print "out of tolerance at", $2}' >> "${log_dir}"/TestExecutionError.txt
                awk '{print "\t\t\t", $0}' $log >> "${log_dir}"/TestExecutionError.txt
            done
        fi
    fi
}

main $@