#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

set -x

trap '' HUP

HOMEDIR=$(pwd)
# Source utils.sh
. utils.sh || {
	echo "ERROR: unable to source utils.sh!"
	echo "TestAborted" > state.txt
	exit 0
}

NTTTCP_REPO="https://github.com/Microsoft/ntttcp-for-linux"
RAID_SETUP_SCRIPT="./CreateRaid.sh"

# Source constants file and initialize most common variables
UtilsInit

function append_date {
    while read line
    do
        echo "[$(date +%Y-%m-%d-%S)] $line"
    done < "${1:-/dev/stdin}"
}

function build_ntttcp {
    if [[ ! $NTTTCP_REPO ]];then
        LogErr "Missing NTTCP repo"
        SetTestStateAborted
        exit 0
    fi
    
    ntttcp_temp_dir="ntttcp_temp"
    ntttcp_source_dir="${ntttcp_temp_dir}/src"
    
    git clone "$NTTTCP_REPO" "$ntttcp_temp_dir"
    if [[ ! -d $ntttcp_source_dir ]];then
        LogErr "Cannot find ntttcp sources"
        SetTestStateAborted
        exit 0
    fi
    
    pushd $ntttcp_source_dir
    make
    if [ $? -ne 0 ]; then
        LogErr "Ntttcp build failed"
        SetTestStateAborted
        exit 0
    fi
    make install
    if [ $? -ne 0 ]; then
        LogErr "Ntttcp install failed"
        SetTestStateAborted
        exit 1
    fi
}

function start_logging {
    config="$1"
    remote_ip="$2"
    log_dir="$3"
    
    export S_TIME_FORMAT="ISO"

    if [[ $config == "server" ]];then
        # Start sysbench
        pushd "/data"
        sysbench --threads=20 fileio --file-test-mode=rndrw --file-total-size=10G prepare
        nohup sysbench --report-interval=10 --threads=20 --test=fileio --file-test-mode=rndrw --file-total-size=10G --time=0 run | append_date > "${log_dir}/sysbench_run.log" &
        popd
        
        # Start ntttcp server
        nohup ntttcp -P 16 -t 0 > "${log_dir}/ntttcp-server.log" &
        sleep 60
        
        # Start iostat
        nohup iostat -x 10 -c -t > "${log_dir}/iostat.log" &
    elif [[ $config == "client" ]];then
        nohup ntttcp -s"$remote_ip" -P 16 -n 4 -l 1 -t 0 > "${log_dir}/ntttcp-client.log" &
    fi
    
    # Start monitoring tools
    nohup mpstat -P ALL 10 | append_date > "${log_dir}/mpstat_${config}.log" &
    nohup sar -n DEV 10 | append_date > "${log_dir}/sar_${config}.log" &
    nohup vmstat -w -t 10 > "${log_dir}/vmstat_${config}.log" &
}

function main {
    while true;do
        case "$1" in
            --log_dir)
                LOG_DIR="$2"
                shift 2;;
            --config)
                CONFIG="$2"
                shift 2;;
            --server_ip)
                SERVER_IP="$2"
                shift 2;;
            --client_ip)
                CLIENT_IP="$2"
                shift 2;;
            --) shift; break ;;
            *) break ;;
        esac
    done
    
    if [[ $CONFIG == "server" && $CLIENT_IP == "" ]] || [[ $CONFIG == "client" && $SERVER_IP == "" ]];then
        LogErr "IP missing for config: $CONFIG"
        SetTestStateAborted
        exit 1
    fi
    if [[ $CONFIG == "server" ]];then
        remote_ip="$CLIENT_IP"
    elif [[ $CONFIG == "client" ]];then
        remote_ip="$SERVER_IP"
    fi
    
    if [[ -d "$LOG_DIR" ]];then
        rm -rf "$LOG_DIR"
    fi
    mkdir $LOG_DIR
    
    update_repos
    install_package make gcc
    
    build_ntttcp
    install_package sysbench sysstat
    
    cd $HOMEDIR
    
    if [[ $CONFIG == "server" ]];then
        if [[ ! -e $RAID_SETUP_SCRIPT ]];then
            LogErr "Cannot find raid setup script"
            SetTestStateAborted
            exit 1
        fi
        chmod +x $RAID_SETUP_SCRIPT
        
        bash $RAID_SETUP_SCRIPT
    fi
    
    start_logging "$CONFIG" "$remote_ip" "$LOG_DIR"
    
}

main $@