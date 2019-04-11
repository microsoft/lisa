#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

CORE_FILES=('drivers/hv/channel.c' 'drivers/hv/channel_mgmt.c' 'drivers/hv/connection.c'
               'drivers/hid/hid-core.c' 'drivers/hid/hid-debug.c' 'drivers/hid/hid-hyperv.c'
               'drivers/hid/hid-input.c' 'drivers/hid/hv.c' 'drivers/hv/hv_balloon.c'
               'drivers/hv/hv_compat.c' 'drivers/hv/hv_fcopy.c' 'drivers/hv/hv_kvp.c'
               'drivers/hv/hv_snapshot.c' 'drivers/hv/hv_util.c' 'drivers/hv/hv_utils_transport.c'
               'drivers/input/serio/hyperv-keyboard.c' 'drivers/video/fbdev/hyperv_fb.c'
               'drivers/net/hyperv/netvsc.c' 'drivers/net/hyperv/netvsc_drv.c'
               'drivers/hv/ring_buffer.c' 'drivers/net/hyperv/rndis_filter.c'
               'drivers/scsi/storvsc_drv.c' 'drivers/hv/vmbus_drv.c')

HV_SOCK_FILES=('drivers/hv/channel.c' 'drivers/hv/channel_mgmt.c' 'drivers/hv/connection.c'
                'drivers/hv/hv_util.c' 'drivers/hv/hv_utils_transport.c' 'drivers/hv/vmbus_drv.c'
                'net/vmw_vsock/af_vsock.c')
                
SRIOV_FILES=('drivers/net/ethernet/mellanox/mlx4/alloc.c' 'drivers/net/ethernet/mellanox/mlx4/catas.c'
             'drivers/net/ethernet/mellanox/mlx4/cmd.c' 'drivers/net/ethernet/mellanox/mlx4/cq.c'
             'drivers/net/ethernet/mellanox/mlx4/eq.c' 'drivers/net/ethernet/mellanox/mlx4/fw.c'
             'drivers/net/ethernet/mellanox/mlx4/fw_qos.c' 'drivers/net/ethernet/mellanox/mlx4/icm.c'
             'drivers/net/ethernet/mellanox/mlx4/intf.c' 'drivers/net/ethernet/mellanox/mlx4/main.c'
             'drivers/net/ethernet/mellanox/mlx4/mcg.c' 'drivers/net/ethernet/mellanox/mlx4/mr.c'
             'drivers/net/ethernet/mellanox/mlx4/pd.c' 'drivers/net/ethernet/mellanox/mlx4/port.c'
             'drivers/net/ethernet/mellanox/mlx4/profile.c' 'drivers/net/ethernet/mellanox/mlx4/qp.c'
             'drivers/net/ethernet/mellanox/mlx4/reset.c' 'drivers/net/ethernet/mellanox/mlx4/sense.c'
             'drivers/net/ethernet/mellanox/mlx4/srq.c' 'drivers/net/ethernet/mellanox/mlx4/resource_tracker.c'
             'drivers/net/ethernet/mellanox/mlx4/en_main.c' 'drivers/net/ethernet/mellanox/mlx4/en_tx.c'
             'drivers/net/ethernet/mellanox/mlx4/en_rx.c' 'drivers/net/ethernet/mellanox/mlx4/en_ethtool.c'
             'drivers/net/ethernet/mellanox/mlx4/en_port.c' 'drivers/net/ethernet/mellanox/mlx4/en_cq.c'
             'drivers/net/ethernet/mellanox/mlx4/en_resources.c' 'drivers/net/ethernet/mellanox/mlx4/en_netdev.c'
             'drivers/net/ethernet/mellanox/mlx4/en_selftest.c' 'drivers/net/ethernet/mellanox/mlx4/en_clock.c')
               
LOG_REL_PATH="/sys/kernel/debug/gcov/"

function generate_file_list {
    test_category="$1"
    
    if [[ $test_category == "sriov" ]];then
        COLLECT_FILES=${SRIOV_FILES[@]}
    elif [[ $test_category == "hv-sock" ]];then
        COLLECT_FILES=${HV_SOCK_FILES[@]}
    else
        COLLECT_FILES=${CORE_FILES[@]}
    fi
}

function install_packages {
    apt -y update
    apt -y install gcc
}

function generate_gcov {
    source_dir=$1
    logs_dir=$2
    dest_dir=$3
    file=$4
    
    file_name=$(basename $file)
    
    pushd "$source_dir"
    if [[ ! -e $file ]];then
        echo "Cannot find specified file: $file"
        popd
        return 0
    fi
    
    log_rel_dir="${file%/*}"
    logs_dir=$(readlink -f "${logs_dir}/${log_rel_dir}")
    if [[ ! -e $logs_dir ]];then
        echo "Cannot find the relative path to the log file"
        popd
        return 0
    fi
    
    gcov -o "$logs_dir" "$file"
    if [[ ! -e "${file_name}.gcov" ]];then
        echo "Cannot find gcov report for file: $file"
        popd
        return 0
    fi
    cp "${file_name}.gcov" $dest_dir
    
    popd
}

function main {
    while true;do
        case "$1" in
            --build_dir)
                BUILD_DIR=$2
                shift 2;;
            --test_category)
                TEST_CATEGORY=$2
                shift 2;;
            --test_name)
                TEST_NAME=$2
                shift 2;;
            --work_dir)
                WORK_DIR=$2
                shift 2;;
            --archive_name)
                ARCHIVE_NAME=$2
                shift 2;;
            --) shift; break ;;
            *) break ;;
        esac
    done
    
    if [[ ! -d "${WORK_DIR}" ]];then
        mkdir -p "${WORK_DIR}"
    fi
    
    # Install packages
    install_packages
    
    # Generate SOURCE_DIR
    if [[ -e "${BUILD_DIR}" ]];then
        SOURCE_DIR="${BUILD_DIR}"
    else
        echo "Cannot find sources directory"
        exit 0
    fi
    
    # Generate LOGS_DIR
    LOGS_DIR="${WORK_DIR}/logs/${TEST_NAME}"
    if [[ -e "$LOGS_DIR" ]];then
        rm -rf "$LOGS_DIR"
    fi
    mkdir -p "$LOGS_DIR"
    if [[ -e "$ARCHIVE_NAME" ]];then
        tar xzf "$ARCHIVE_NAME" -C "$LOGS_DIR"
    else
        echo "Cannot find logs archive"
        exit 0
    fi
    LOGS_DIR="${LOGS_DIR}/${LOG_REL_PATH}/${BUILD_DIR}"
    LOGS_DIR="$(readlink -f $LOGS_DIR)"
    if [[ ! -d "${LOGS_DIR}" ]];then
        echo "Cannot find final log directory"
        exit 0
    fi
    
    # Generate DEST_DIR
    DEST_DIR="${WORK_DIR}/gcov/${TEST_NAME}"
    if [[ -e "$DEST_DIR" ]];then
        rm -rf "$DEST_DIR"
    fi
    mkdir -p $DEST_DIR
    
    generate_file_list $TEST_CATEGORY
    
    # Working with SOURCE_DIR, LOGS_DIR, DEST_DIR
    for file in ${COLLECT_FILES[@]};do
        generate_gcov $SOURCE_DIR $LOGS_DIR $DEST_DIR $file
    done
}

main $@