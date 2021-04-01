#!/bin/bash

# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
#     Description: This verifies if the interrupts count from
# /proc/interrupts is increasing after traffic went through the VFs.
# Expected initial results:
#    a. The number of PCIe MSI devices processing interrupts should be greater
#       than NUM_VF*9
# 1.On the controller-vm save/construct these values from /proc/interrupts:
#    a. A sum of all interrupts per PCIe MSI device (exclude MSI devices
#       with 0 interrupts)
#    b. A list of all vCPUs that are processing interrupts. Save the number of
#       interrupts for each vCPU.
# 2.Start iPerf3 for 10 minutes with 128 threads
# 3.Repeat step 2 after iPerf3 finished
# Expected results:
#    After comparing the values from step 2 and step 4, each value from step 4
# should increase after the iPerf3 run.
#
########################################################################
remote_user="root"
declare -a initial_cpu_interrupts
declare -a final_cpu_interrupts
declare -a initial_pci_interrupts
declare -a final_pci_interrupts
declare final_cpu_processing_interrupts_count

function get_interrupts_per_pci() {
    pci_processing_interrupts_count=0
    pci_interrupt_values=()
    while read line
    do
        msi_value=$(echo $line | grep -i MSI | awk '{ for(i=2; i<='"$(($(nproc)+1))"'; ++i) { sum+=$i }; print sum }')
        if [ -n "${msi_value-}" ]; then
            if [ $msi_value -ne "0" ]; then
                pci_interrupt_values+=("$msi_value")
                ((pci_processing_interrupts_count++))
            fi
        fi
    done < "/proc/interrupts"

    if [[ $(($vf_count*9)) -gt $pci_processing_interrupts_count ]] && \
       [[ "$1" -eq "2" ]]; then
        LogErr "The number of PCI devices processing interrupts is smaller than expected!"
        SetTestStateFailed
        exit 0
    else
        LogMsg "The number of PCI devices processing interrupts is: $pci_processing_interrupts_count"
    fi

    # $1 -eq 1 means it will construct the initial array of the interrupts/PCIe
    # $1 -eq 2 means it will construct the final array of the interrupts/PCIe
    if [ "$1" -eq "1" ]; then
        initial_pci_interrupts=( "${pci_interrupt_values[@]}" )
    else
        final_pci_interrupts=( "${pci_interrupt_values[@]}" )
    fi
}

function get_interrupts_per_vcpu() {
    cpu_processing_interrupts_count=0
    cpu_array=()
    for (( vcpu_line=1; vcpu_line<=$(nproc); vcpu_line++ ))
    do
        line=$(cat /proc/interrupts | grep -i MSI | awk '{$1=""} { for(i=2; i<='"$(($(nproc)+1))"'; i++) { { printf"%1s ", $i } if(i=='"$(($(nproc)+1))"') printf"\n"; }; }' \
             | awk '
             {
                 for (i=1; i<=NF; i++)  {
                     a[NR,i] = $i
                 }
             }
             NF>p { p = NF }
             END {
                 for(j=1; j<=p; j++) {
                     str=a[1,j]
                     for(i=2; i<=NR; i++){
                         str=str"\t"a[i,j];
                     }
                     print str
                 }
             }' | head -"$vcpu_line" | tail -1)
        vcpu_number=$(($vcpu_line-1))
        interrupts_sum=$(echo $line | awk '{sum=0; for(i=1; i<=NF; i++) sum += $i; print sum}')
        cpu_array[$vcpu_number]+=$interrupts_sum
        LogMsg "vCPU $vcpu_number is processing $interrupts_sum interrupts"
        if [ "$interrupts_sum" -gt "0" ]; then
            ((cpu_processing_interrupts_count++))
        fi
    done

    # $1 -eq 1 means it will construct the initial array of the interrupts/vCPU
    # $1 -eq 2 means it will construct the final array of the interrupts/vCPU
    if [ "$1" -eq "1" ]; then
        LogMsg "The initial number of vCPUs processing interrupts is: $cpu_processing_interrupts_count"
        initial_cpu_interrupts=( "${cpu_array[@]}" )
    else
        LogMsg "After iPerf3 run, the number of vCPUs processing interrupts is: $cpu_processing_interrupts_count"
        final_cpu_processing_interrupts_count=$cpu_processing_interrupts_count
        final_cpu_interrupts=( "${cpu_array[@]}" )
    fi
}

if [ ! -e sriov_constants.sh ]; then
    cp /${remote_user}/sriov_constants.sh .
fi
export PATH="/usr/local/bin:${PATH}"

# Source SR-IOV_Utils.sh
. SR-IOV-Utils.sh || {
    echo "ERROR: unable to source SR-IOV_Utils.sh!"
    echo "TestAborted" > state.txt
    exit 0
}
UtilsInit

if [[ $(detect_linux_distribution) == coreos ]]; then
    iperf3_cmd="docker run --network host lisms/iperf3"
else
    iperf3_cmd="iperf3"
fi

# Check if the VF count inside the VM is the same as the expected count
vf_count=$(get_vf_count)
if [ "$vf_count" -ne "$NIC_COUNT" ]; then
    LogErr "Expected VF count: $NIC_COUNT. Actual VF count: $vf_count"
    SetTestStateFailed
    exit 0
fi
UpdateSummary "Expected VF count: $NIC_COUNT. Actual VF count: $vf_count"

# Get initial values of PCIe MSI devices processing interrupts and
# values for each vCPU
get_interrupts_per_pci "1"
# Compute an array with interrupts/vCPU before the traffic starts
get_interrupts_per_vcpu "1"

# Start iPerf3 to force the interrupt count to increase
LogMsg "------------ Running iPerf3 for 10 minutes ------------"
ssh -i "$HOME"/.ssh/"$SSH_PRIVATE_KEY" -o StrictHostKeyChecking=no "$remote_user"@"$VF_IP2" "nohup $iperf3_cmd -s > /dev/null 2>&1 &"
sleep 5
$iperf3_cmd -t 600 -c $VF_IP2 -P 128
if [ $? -eq 0 ]; then
    LogMsg "------------ iPerf3 run has finished ------------"
else
    LogErr "iPerf3 failed to run!"
    SetTestStateFailed
    exit 0
fi

# Get initial values of PCIe MSI devices processing interrupts and
# values for each vCPU
get_interrupts_per_pci "2"
# Compute an array with interrupts/vCPU after the traffic stopped
get_interrupts_per_vcpu "2"

# Compare the final arrays with the initial arrays
pci_len=${#initial_pci_interrupts[@]}
for (( pci=0; pci<$pci_len; pci++ ))
do
    if [ "${initial_pci_interrupts[$pci]}" -ge "${final_pci_interrupts[$pci]}" ]; then
        LogErr "At least one PCI device didn't have an increased interrupt count after iPerf3 run!"
        SetTestStateFailed
        exit 0
    fi
done

cpu_len=${#initial_cpu_interrupts[@]}
unused_cpu=0
for (( cpu=0; cpu<$cpu_len; cpu++ ))
do
    if [[ "${initial_cpu_interrupts[$cpu]}" -ge "${final_cpu_interrupts[$cpu]}" ]] && \
       [[ "${initial_cpu_interrupts[$cpu]}" -gt "50" ]]; then
        ((unused_cpu++))
    else
        if [ "${initial_cpu_interrupts[$cpu]}" -ne "${final_cpu_interrupts[$cpu]}" ]; then
            LogMsg "vCPU $cpu interrupts increased from ${initial_cpu_interrupts[$cpu]} to ${final_cpu_interrupts[$cpu]}"
        fi
    fi
done

if [ $unused_cpu -ge $(($final_cpu_processing_interrupts_count/2)) ]; then
    LogErr "More than half of the vCPUs didn't have increased interrupt count!"
    SetTestStateFailed
    exit 0
fi

UpdateSummary "The interrupts increased as expected!"
SetTestStateCompleted
exit 0
