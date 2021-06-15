#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
Log() {
    msg="$1"
    cmd="$2"
    file="$3"
    {
        echo "$msg"
        echo "Command Used:$cmd"
        eval "$cmd"
    } >> "$file"
}

intro() {
    ##Create the Directory in Which Logs would be stored
    #dirname="LIS-Logs-"${hostnm};
    dirname="LIS-Logs"
    mkdir $dirname;
}

Collect_Waagent_Logs() {
    echo "Collecting Waagent Details...."
    Log "Collecting Waagent Details at" 'date' $dirname/Waagent.txt
    Log "Waagent Process Running Status" 'ps -ef | grep waagent' $dirname/Waagent.txt
    if [ -f /usr/share/oem/bin/waagent ]
    then
        Log "Waagent Version is" '/usr/share/oem/python/bin/python /usr/share/oem/bin/waagent --version' $dirname/Waagent.txt
    elif [ -f /bin/waagent ]
    then
        Log "Waagent Version is" '/bin/waagent --version' $dirname/Waagent.txt
    else
        Log "Waagent Version is" '/usr/sbin/waagent --version' $dirname/Waagent.txt
    fi
    Log "Root Device Timeout" 'cat /sys/block/sda/device/timeout' $dirname/Waagent.txt
    if [[ $dist == *Debian* ]] || [[  $dist == *Ubuntu* ]]
    then
        Log "Waagent Package Details" 'dpkg-query -l walinuxagent' $dirname/Waagent.txt
    else
        Log "Waagent Package Details" 'rpm -qil WALinuxAgent' $dirname/Waagent.txt
    fi
    Log "Waagent.log file" 'cat /var/log/waagent.log' $dirname/Waagent.log
}

Collect_OS_Logs() {
    echo "Collecting Operating System Logs....."
    Log "Collecting Operating System Details at" 'date' $dirname/OS.log
    Log "Kernel Version" 'uname -a' $dirname/OS.log
    if [ -f "/etc/issue" ]; then
        Log "Distro Release Details" 'cat /etc/issue' $dirname/OS.log
    else
        return
    fi
    Log "Additional Kernel Details" 'sudo cat /proc/version' $dirname/OS.log
    Log "Mount Points" 'mount' $dirname/OS.log
    Log "System Limits" 'ulimit -a' $dirname/OS.log
    #Log "NFS Shares on System" 'showmount -e' $dirname/OS.log
    Log "Hosts File Details" 'cat /etc/hosts' $dirname/OS.log
    Log "Locale Details" 'locale' $dirname/OS.log
    Log "Running Process Details" 'ps -auwwx' $dirname/OS.log
    if [ -e /boot/grub/grub.conf ]; then
        Log "Grub File Details" 'cat /boot/grub/grub.conf' $dirname/grub.log
        elif [ -e /boot/grub/menu.lst ]; then
        Log "Grub File Details" 'cat /boot/grub/menu.lst' $dirname/grub.log
        elif [ -e /etc/grub.conf ]; then
        Log "Grub File Details" 'cat /etc/grub.conf' $dirname/grub.log
    fi
    Log "Enviornment Variables Settings"  'env' $dirname/OS.log
    Log "Dmesg File Details" 'dmesg' $dirname/dmesg.txt
    dist=$(cat /etc/issue)
    echo "$dist"
    if [[ $dist == *Debian* ]] || [[  $dist == *Ubuntu* ]]
    then
        Log "Kernel Loaded Packages" 'dpkg -l | grep kernel' $dirname/KernelPackagess.txt
    else
        Log "Kernel Loaded Packages" 'rpm -qa | grep kernel' $dirname/KernelPackages.txt
    fi
    #Log "var log messages saved" 'cat /var/log/messages' $dirname/VarLogMessages.txt
    Log "System has Been up since" 'uptime' $dirname/OS.log
    echo "Operating system Log process finished..."
    Log "I/O Scheduler Details" 'cat /sys/block/sda/queue/scheduler ' $dirname/OS.log
}

Collect_LIS() {
    echo "Collecting Microsoft Linux Integration Service Data..."
    HYPERV_MODULES=()
    HYPERV_MODULES+=$(lsmod | grep vsc | cut -d' ' -f1)
    skip_modules=()
    config_path="/boot/config-$(uname -r)"
    declare -A config_modulesDic
    config_modulesDic=(
    [CONFIG_HYPERV=y]="hv_vmbus"
    [CONFIG_HYPERV_STORAGE=y]="hv_storvsc"
    )
    for key in $(echo ${!config_modulesDic[*]})
    do
        module_included=$(grep $key "$config_path")
        if [ "$module_included" ]; then
            skip_modules+=("${config_modulesDic[$key]}")
            echo "Info: Skiping ${config_modulesDic[$key]} module as it is built-in."
        fi
    done
    # Remove each module in HYPERV_MODULES from skip_modules
    for mod in "${HYPERV_MODULES[@]}"; do
        TEMP_HYPERV_MODULES=()
        for remove in "${skip_modules[@]}"; do
            KEEP=true
            if [[ ${mod} == ${remove} ]]; then
                KEEP=false
                break
            fi
        done
        if ${KEEP}; then
            TEMP_HYPERV_MODULES+=(${mod})
        fi
    done
    HYPERV_MODULES=("${TEMP_HYPERV_MODULES[@]}")
    # SLES has all modules built in to the  kernel
    if [ -z "$HYPERV_MODULES" ]; then
        echo "All modules built-in ..."
    else
        unset TEMP_HYPERV_MODULES
    fi
    for module in "${HYPERV_MODULES[@]}"; do
        version=$(modinfo "$module" | grep vermagic: | head -1 | awk '{print $2}')
        echo "$module module: ${version}"
        continue
    done
    Log "LIS Modules Loaded" "lsmod | grep vsc | cut -d' ' -f1" $dirname/LISDetails.txt
    echo "Collecting Microsoft Linux Integration Service Data Finished..."
}

Collect_DiskandMemory() {
    echo "Collecting Disk and Memory Data"
    Log "Disk Partition Details" 'fdisk -l' $dirname/Disk.txt
    Log "Filesystem details" 'df -k' $dirname/Disk.txt
    Log "Additional Partition Details" 'cat /proc/partitions' $dirname/Disk.txt
    Log "Memory Details" 'cat /proc/meminfo' $dirname/Memory.txt
    Log "Scsi details" 'cat /proc/scsi/scsi' $dirname/Disk.txt
    Log "Memory Usage Details in MB" 'free -m' $dirname/Memory.txt
    Log "I/O Memory details" 'cat /proc/iomem' $dirname/Memory.txt
    echo "Collecting Disk and Memory Data Finished..."
}

Collect_Processor() {
    echo "Collecting Processor Data..."
    Log "Processor Details" 'cat /proc/cpuinfo' $dirname/Cpuinfo.txt
    Log "Processor Count" 'cat /proc/cpuinfo | grep ^proc' $dirname/Cpuinfo.txt
    Log "Interrupts details" 'cat /proc/interrupts' $dirname/interrupts.txt
    Log "List of loaded Modules" 'lsmod' $dirname/Modules.txt
    Log "List of IO Ports" 'cat /proc/ioports' $dirname/IOports.txt
    Log "Processor Real time activity" 'top -b -n 5' $dirname/Top.txt
    Log "Processes consuming most amount of memory" 'ps -eo pcpu,pid,user,args | sort -k 1 -r | head -10' $dirname/Top.txt
    echo "Collecting Processor Data Finished..."
}

Collect_Network() {
    ip=$(command -v ip )
    netstat=$(command -v netstat)
    route=$(command -v netstat)
    echo "Collecting Network Data..."
    if ! [ "$ip" ]; then
        echo "ip is not installed"
    else
        Log "Network Interface Details" 'ip a' $dirname/Network.txt
    fi
    if ! [ "$netstat" ]; then
        echo "netstat is not installed"
    else
        Log "Network Status Details by interface" 'netstat -i' $dirname/Network.txt
        Log "Network Status Details of all sockets" 'netstat -a' $dirname/Network.txt
        Log "Network Status Details Source and Destinations ips and ports" 'netstat -lan' $dirname/Network.txt
    fi
    if ! [ "$route" ]; then
        echo "route is not installed"
    else
    Log "Routing Table Details" 'route' $dirname/Route.txt
    echo "Collecting Network Data Finished..."
    fi
}

Create_Compr_Logs() {
    echo "Compressing Logs"
    tar -czf $dirname.tgz $dirname/*
}

Upload_Logs() {
    return;
}

intro
Collect_OS_Logs
Collect_Waagent_Logs
Collect_LIS
Collect_DiskandMemory
Collect_Processor
Collect_Network
Create_Compr_Logs

