#!/bin/bash

# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
# Description:
# 1. Keep running traffic between two VMs in background.
# 2. Repeat the load and unload every 5 seconds.
# 3. Check the VF is still working.
########################################################################
remote_user="root"
if [ ! -e sriov_constants.sh ]; then
    cp /${remote_user}/sriov_constants.sh .
fi
# Source SR-IOV_Utils.sh. This is the script that contains all the 
# SR-IOV basic functions (checking drivers, checking VFs, assigning IPs)
. SR-IOV-Utils.sh || {
    echo "ERROR: unable to source SR-IOV_Utils.sh!"
    echo "TestAborted" > state.txt
    exit 0
}

# Check if the SR-IOV driver is in use
VerifyVF
if [ $? -ne 0 ]; then
    LogErr "VF is not loaded! Make sure you are using compatible hardware"
    SetTestStateFailed
    exit 0
fi

export PATH="/usr/local/bin:${PATH}"
SetTestStateRunning

#Start iperf in server mode on the dependency vm
LogMsg "Starting iperf in server mode on ${VF_IP2}"
ssh -i "$HOME"/.ssh/"$SSH_PRIVATE_KEY" -o StrictHostKeyChecking=no ${remote_user}@${VF_IP2} "nohup iperf3 -s > client.out &" > /dev/null 2>&1
if [ $? -ne 0 ]; then
    LogErr "Unable to start iperf server script on the dependency vm."
    SetTestStateFailed
    exit 0
fi

cat > Start_Iperf_Client.sh << EOF
while true
do
    iperf3 -t 30 -c $VF_IP2 --logfile PerfResults.log
    sleep 1
done
EOF

bash Start_Iperf_Client.sh &

for ((counter=1; counter<10; ++counter))
do
    LogMsg "The $counter iterations to disable and enable the VF device"
    # Disable the VF
    vf_pci_address=$(lspci | grep -i Ethernet | awk '{ print $1 }')
    vf_pci_remove_path="/sys/bus/pci/devices/${vf_pci_address}/remove"
    if [ ! -f $vf_pci_remove_path ]; then
        LogErr "Unable to disable the VF, because the $vf_pci_remove_path doesn't exist"
        SetTestStateFailed
        exit 0
    fi
    echo 1 > $vf_pci_remove_path
    sleep 5

    # Using the lspci command, verify if NIC has SR-IOV support
    lspci -vvv | grep 'mlx4_core\|mlx4_en\|ixgbevf'
    if [ $? -eq 0 ]; then
        LogErr "Disable the VF device failed at $counter iterations"
        SetTestStateFailed
        exit 0
    fi

    # Enable the VF
    echo 1 > /sys/bus/pci/rescan
    sleep 5
    VerifyVF
    if [ $? -ne 0 ]; then
        LogErr "VF is not loaded! Enable the VF device failed at $counter iterations"
        SetTestStateFailed
        exit 0
    fi
done

if [ -z "$VF_IP1" ]; then
    vf_interface=$(ls /sys/class/net/ | grep -v 'eth0\|eth1\|lo' | head -1)
else
    synthetic_interface=$(ip addr | grep "$VF_IP1" | awk '{print $NF}')
    vf_interface=$(find /sys/devices/* -name "*${synthetic_interface}" | grep "pci" | sed 's/\// /g' | awk '{print $12}')
fi

# Check the VF is still working
tx_value=$(cat /sys/class/net/"${vf_interface}"/statistics/tx_packets)
sleep 4
tx_value_current=$(cat /sys/class/net/"${vf_interface}"/statistics/tx_packets)
diff=$(expr $tx_value_current - $tx_value)
if [ "$diff" -lt 50000 ]; then
    LogErr "Insufficient TX packets sent on ${vf_interface}"
    SetTestStateFailed
    exit 0
fi

UpdateSummary "Successfully disabled and enabled the VF device"
SetTestStateCompleted
exit 0