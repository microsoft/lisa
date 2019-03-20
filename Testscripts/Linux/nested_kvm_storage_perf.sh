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
UTIL_FILE="./nested_vm_utils.sh"
CONSTANTS_FILE="./constants.sh"
ImageName="nested.qcow2"

. ${CONSTANTS_FILE} || {
    errMsg="Error: missing ${CONSTANTS_FILE} file"
    LogMsg "${errMsg}"
    Update_Test_State $ICA_TESTABORTED
    exit 10
}
. ${UTIL_FILE} || {
    errMsg="Error: missing ${UTIL_FILE} file"
    LogMsg "${errMsg}"
    Update_Test_State $ICA_TESTABORTED
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
    Update_Test_State $ICA_TESTABORTED
    echo "RaidOption $RaidOption is invalid"
    exit 0
fi

touch $logFolder/state.txt
log_file=$logFolder/$(basename "$0").log
touch $log_file

Remove_Raid()
{
    Log_Msg "INFO: Check and remove RAID first" $log_file
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

Prepare_Nested_VM()
{
    #Prepare command for start nested kvm
    cmd="qemu-system-x86_64 -machine pc-i440fx-2.0,accel=kvm -smp $NestedCpuNum -m $NestedMemMB -hda $ImageName -display none -device e1000,netdev=user.0 -netdev user,id=user.0,hostfwd=tcp::$HostFwdPort-:22 -enable-kvm -daemonize"
    for disk in ${disks}
    do
        echo "add disk /dev/${disk} to nested VM"
        cmd="${cmd} -drive id=datadisk-${disk},file=/dev/${disk},cache=none,if=none,format=raw,aio=threads -device virtio-scsi-pci -device scsi-hd,drive=datadisk-${disk}"
    done

    #Prepare nested kvm
    Start_Nested_VM -user $NestedUser -passwd $NestedUserPassword -port $HostFwdPort $cmd
    Enable_Root -user $NestedUser -passwd $NestedUserPassword -port $HostFwdPort
    Reboot_Nested_VM -user root -passwd $NestedUserPassword -port $HostFwdPort
}

Run_Fio()
{
    Log_Msg "Copy necessary scripts to nested VM" $log_file
    remote_copy -host localhost -user root -passwd $NestedUserPassword -port $HostFwdPort -filename ./utils.sh -remote_path /root -cmd put
    remote_copy -host localhost -user root -passwd $NestedUserPassword -port $HostFwdPort -filename ./StartFioTest.sh -remote_path /root -cmd put
    remote_copy -host localhost -user root -passwd $NestedUserPassword -port $HostFwdPort -filename ./constants.sh -remote_path /root -cmd put
    remote_copy -host localhost -user root -passwd $NestedUserPassword -port $HostFwdPort -filename ./ParseFioTestLogs.sh -remote_path /root -cmd put
    remote_copy -host localhost -user root -passwd $NestedUserPassword -port $HostFwdPort -filename ./nested_kvm_perf_fio.sh -remote_path /root -cmd put
    remote_copy -host localhost -user root -passwd $NestedUserPassword -port $HostFwdPort -filename ./fio_jason_parser.sh -remote_path /root -cmd put
    remote_copy -host localhost -user root -passwd $NestedUserPassword -port $HostFwdPort -filename ./gawk -remote_path /root -cmd put
    remote_copy -host localhost -user root -passwd $NestedUserPassword -port $HostFwdPort -filename ./JSON.awk -remote_path /root -cmd put

    Log_Msg "Start to run StartFioTest.sh on nested VM" $log_file
    remote_exec -host localhost -user root -passwd $NestedUserPassword -port $HostFwdPort '/root/StartFioTest.sh'
}

Collect_Logs()
{
    Log_Msg "Finished running StartFioTest.sh, start to collect logs" $log_file
    remote_copy -host localhost -user root -passwd $NestedUserPassword -port $HostFwdPort -filename fioConsoleLogs.txt -remote_path "/root" -cmd get
    remote_copy -host localhost -user root -passwd $NestedUserPassword -port $HostFwdPort -filename runlog.txt -remote_path "/root" -cmd get
    remote_copy -host localhost -user root -passwd $NestedUserPassword -port $HostFwdPort -filename state.txt -remote_path "/root" -cmd get
    state=$(cat state.txt)
    Log_Msg "FIO Test state: $state" $log_file
    if [ $state == 'TestCompleted' ]; then
        remote_exec -host localhost -user root -passwd $NestedUserPassword -port $HostFwdPort '/root/ParseFioTestLogs.sh'
        remote_copy -host localhost -user root -passwd $NestedUserPassword -port $HostFwdPort -filename FIOTest-*.tar.gz -remote_path "/root" -cmd get
        remote_copy -host localhost -user root -passwd $NestedUserPassword -port $HostFwdPort -filename perf_fio.csv -remote_path "/root" -cmd get
        remote_copy -host localhost -user root -passwd $NestedUserPassword -port $HostFwdPort -filename nested_properties.csv -remote_path "/root" -cmd get
    else
        Update_Test_State $ICA_TESTFAILED
        exit 0
    fi
}

############################################################
#   Main body
############################################################
Update_Test_State $ICA_TESTRUNNING

disks=$(ls -l /dev | grep sd[c-z]$ | awk '{print $10}')
Remove_Raid

if [[ $RaidOption == 'RAID in L1' ]]; then
    mdVolume="/dev/md0"
    create_raid0 "$disks" $mdVolume
    if [ $? -ne 0 ]; then
        Update_Test_State $ICA_TESTFAILED
        exit 0
    fi
    disks='md0'
fi

for disk in ${disks}
do
    Log_Msg "set rq_affinity to 0 for device ${disk}" $log_file
    echo 0 > /sys/block/${disk}/queue/rq_affinity
done

Install_KVM_Dependencies

Download_Image_Files -destination_image_name $ImageName -source_image_url $NestedImageUrl

#Prepare nested kvm
Prepare_Nested_VM

#Run fio test
Run_Fio

#Collect test logs
Collect_Logs
Stop_Nested_VM
collect_VM_properties
Update_Test_State $ICA_TESTCOMPLETED