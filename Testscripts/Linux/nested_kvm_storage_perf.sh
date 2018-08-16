#!/bin/bash

#######################################################################
#
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
#######################################################################

#######################################################################
#
# nested_kvm_storage_perf.sh
#
# Description:
#   This script prepares nested kvm for fio test.
#
#######################################################################

while echo $1 | grep -q ^-; do
   declare $( echo $1 | sed 's/^-//' )=$2
   shift
   shift
done

#
# Constants/Globals
#
UTIL_FILE="./nested_kvm_utils.sh"
CONSTANTS_FILE="./constants.sh"
ImageName="nested.qcow2"

. ${CONSTANTS_FILE} || {
    errMsg="Error: missing ${CONSTANTS_FILE} file"
    log_msg "${errMsg}"
    update_test_state $ICA_TESTABORTED
    exit 10
}
. ${UTIL_FILE} || {
    errMsg="Error: missing ${UTIL_FILE} file"
    log_msg "${errMsg}"
    update_test_state $ICA_TESTABORTED
    exit 10
}

if [ -z "$NestedImageUrl" ]; then
    echo "Please mention -NestedImageUrl next"
    exit 1
fi
if [ -z "$NestedUser" ]; then
    echo "Please mention -NestedUser next"
    exit 1
fi
if [ -z "$NestedUserPassword" ]; then
    echo "Please mention -NestedUserPassword next"
    exit 1
fi
if [ -z "$NestedCpuNum" ]; then
    echo "Please mention -NestedCpuNum next"
    exit 1
fi
if [ -z "$NestedMemMB" ]; then
    echo "Please mention -NestedMemMB next"
    exit 1
fi
if [ -z "$TestPlatform" ]; then
    echo "Please mention -platform next"
    exit 1
fi
if [ -z "$RaidOption" ]; then
    echo "Please mention -RaidOption next"
    exit 1
fi
if [ -z "$logFolder" ]; then
    logFolder="."
    echo "-logFolder is not mentioned. Using ."
else
    echo "Using Log Folder $logFolder"
fi
if [[ $RaidOption == 'RAID in L1' ]] || [[ $RaidOption == 'RAID in L2' ]] || [[ $RaidOption == 'No RAID' ]]; then
    echo "RaidOption is available"
else
    update_test_state $ICA_TESTABORTED
    echo "RaidOption $RaidOption is invalid"
    exit 0
fi

touch $logFolder/state.txt
touch $logFolder/`basename "$0"`.log

log_msg()
{
    echo `date "+%b %d %Y %T"` : "$1" >> $logFolder/`basename "$0"`.log
}

remove_raid()
{
    log_msg "INFO: Check and remove RAID first"
    mdvol=$(cat /proc/mdstat | grep md | awk -F: '{ print $1 }')
    if [ -n "$mdvol" ]; then
        echo "/dev/${mdvol} already exist...removing first"
        umount /dev/${mdvol}
        mdadm --stop /dev/${mdvol}
        mdadm --remove /dev/${mdvol}
        for disk in ${disks}
        do
            echo "formatting disk /dev/${disk}"
            mkfs -t ext4 -F /dev/${disk}
        done
    fi
}

create_raid0()
{
    log_msg "INFO: Creating Partitions"
    count=0
    for disk in ${disks}
    do
        echo "formatting disk /dev/${disk}"
        (echo d; echo n; echo p; echo 1; echo; echo; echo t; echo fd; echo w;) | fdisk /dev/${disk}
        count=$(( $count + 1 ))
        sleep 1
    done
    log_msg "INFO: Creating RAID of ${count} devices."
    yes | mdadm --create ${mdVolume} --level 0 --raid-devices ${count} /dev/${devices}[1-5]
    if [ $? -ne 0 ]; then
        update_test_state $ICA_TESTFAILED
        log_msg "Error: Unable to create raid"
        exit 0
    else
        log_msg "Create raid successfully."
    fi
}

prepare_nested_vm()
{
    #Prepare command for start nested kvm
    cmd="qemu-system-x86_64 -machine pc-i440fx-2.0,accel=kvm -smp $NestedCpuNum -m $NestedMemMB -hda $ImageName -display none -device e1000,netdev=user.0 -netdev user,id=user.0,hostfwd=tcp::$HostFwdPort-:22 -enable-kvm -daemonize"
    for disk in ${disks}
    do
        echo "add disk /dev/${disk} to nested VM"
        cmd="${cmd} -drive id=datadisk-${disk},file=/dev/${disk},cache=none,if=none,format=raw,aio=threads -device virtio-scsi-pci -device scsi-hd,drive=datadisk-${disk}"
    done

    #Prepare nested kvm
    start_nested_vm -user $NestedUser -passwd $NestedUserPassword -port $HostFwdPort $cmd
    enable_root -user $NestedUser -passwd $NestedUserPassword -port $HostFwdPort
    reboot_nested_vm -user root -passwd $NestedUserPassword -port $HostFwdPort
}

run_fio()
{
    log_msg "Copy necessary scripts to nested VM"
    remote_copy -host localhost -user root -passwd $NestedUserPassword -port $HostFwdPort -filename ./utils.sh -remote_path /root -cmd put
    remote_copy -host localhost -user root -passwd $NestedUserPassword -port $HostFwdPort -filename ./StartFioTest.sh -remote_path /root -cmd put
    remote_copy -host localhost -user root -passwd $NestedUserPassword -port $HostFwdPort -filename ./constants.sh -remote_path /root -cmd put
    remote_copy -host localhost -user root -passwd $NestedUserPassword -port $HostFwdPort -filename ./ParseFioTestLogs.sh -remote_path /root -cmd put
    remote_copy -host localhost -user root -passwd $NestedUserPassword -port $HostFwdPort -filename ./nested_kvm_perf_fio.sh -remote_path /root -cmd put

    log_msg "Start to run StartFioTest.sh on nested VM"
    remote_exec -host localhost -user root -passwd $NestedUserPassword -port $HostFwdPort '/root/StartFioTest.sh'
}

collect_logs()
{
    log_msg "Finished running StartFioTest.sh, start to collect logs"
    remote_copy -host localhost -user root -passwd $NestedUserPassword -port $HostFwdPort -filename fioConsoleLogs.txt -remote_path "/root" -cmd get
    remote_copy -host localhost -user root -passwd $NestedUserPassword -port $HostFwdPort -filename runlog.txt -remote_path "/root" -cmd get
    remote_copy -host localhost -user root -passwd $NestedUserPassword -port $HostFwdPort -filename state.txt -remote_path "/root" -cmd get
    state=`cat state.txt`
    log_msg "FIO Test state: $state"
    if [ $state == 'TestCompleted' ]; then
        remote_exec -host localhost -user root -passwd $NestedUserPassword -port $HostFwdPort '/root/ParseFioTestLogs.sh'
        remote_copy -host localhost -user root -passwd $NestedUserPassword -port $HostFwdPort -filename FIOTest-*.tar.gz -remote_path "/root" -cmd get
        remote_copy -host localhost -user root -passwd $NestedUserPassword -port $HostFwdPort -filename perf_fio.csv -remote_path "/root" -cmd get
        remote_copy -host localhost -user root -passwd $NestedUserPassword -port $HostFwdPort -filename nested_properties.csv -remote_path "/root" -cmd get
    else
        update_test_state $ICA_TESTFAILED
        exit 0
    fi
}

############################################################
#   Main body
############################################################
update_test_state $ICA_TESTRUNNING

if [[ $TestPlatform == 'HyperV' ]]; then
    devices='sd[b-z]'
else
    devices='sd[c-z]'
fi

disks=$(ls -l /dev | grep ${devices}$ | awk '{print $10}')
remove_raid

if [[ $RaidOption == 'RAID in L1' ]]; then
    mdVolume="/dev/md0"
    create_raid0
    disks='md0'
fi

for disk in ${disks[@]}
do
    log_msg "set rq_affinity to 0 for device ${disk}"
    echo 0 > /sys/block/${disk}/queue/rq_affinity
done

install_kvm_dependencies

download_image_files -destination_image_name $ImageName -source_image_url $NestedImageUrl

#Prepare nested kvm
prepare_nested_vm

#Run fio test
run_fio

#Collect test logs
collect_logs
stop_nested_vm
collect_VM_properties
update_test_state $ICA_TESTCOMPLETED