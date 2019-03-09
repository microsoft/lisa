#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

###############################################################################
#
# Description:
#   This script verifies that the network doesn't loose connection
#   by trigerring two scp processes that copy two files, at the same time,
#   between the two VMs.
#
#   Steps:
#   1. Verify configuration file constants.sh
#   2. Verify ssh private key file for remote VM was given
#   3. Ping the remote server through the Synthetic Adapter card
#   4. Verify there is enough local and remote disk space for 20GB
#   5. Create two 10GB files, one on the local VM and one on the remote VM, 
#      from /dev/urandom
#   6. Save md5sums and start copying the two files.
#   7. Compare md5sums for both cases
#
###############################################################################
tmp="/tmp"
remote_user="root"
homeDir="/home/${SUDO_USER}"

. net_constants.sh || {
    echo "unable to source net_constants.sh!"
    echo "TestAborted" > state.txt
    exit 2
}
# Source utils.sh
. utils.sh || {
    echo "unable to source utils.sh!"
    echo "TestAborted" > state.txt
    exit 2
}
# Source constants file and initialize most common variables
UtilsInit

# Check and set parameters
if [ "${STATIC_IP:-UNDEFINED}" = "UNDEFINED" ]; then
    LogErr "The test parameter STATIC_IP is not defined in constants file"
    SetTestStateAborted
    exit 0
fi
if [ "${STATIC_IP2:-UNDEFINED}" = "UNDEFINED" ]; then
    LogErr "The test parameter STATIC_IP2 is not defined in constants file"
    SetTestStateAborted
    exit 0
fi
if [ "${SSH_PRIVATE_KEY:-UNDEFINED}" = "UNDEFINED" ]; then
    LogErr "The test parameter SSH_PRIVATE_KEY is not defined in constants file"
    SetTestStateAborted
    exit 0
fi
if [ "${NETMASK:-UNDEFINED}" = "UNDEFINED" ]; then
    LogMsg "The test parameter NETMASK is not defined in constants file . Defaulting to 255.255.255.0"
    NETMASK=255.255.255.0
fi
if [ "${NO_DELETE:-UNDEFINED}" = "UNDEFINED" ]; then
    LogMsg "The test parameter NO_DELETE is not defined in constants. Generated file will be deleted"
    NO_DELETE=0
else
    NO_DELETE=1
    LogMsg "NO_DELETE is set. Generated file will not be deleted"
fi
# Parameter provided in constants file
if [ "${ipv4:-UNDEFINED}" = "UNDEFINED" ]; then
    LogErr "The test parameter ipv4 is not defined in constants file"
    SetTestStateAborted
    exit 0
else
    # Get the interface associated with the given ipv4
    iface_ignore=$(ip -o addr show| grep "$ipv4" | cut -d ' ' -f2)
fi

# Retrieve synthetic network interfaces
GetSynthNetInterfaces
if [ 0 -ne $? ]; then
    LogErr "No synthetic network interfaces found"
    SetTestStateFailed
    exit 0
fi

# Remove interface if present
SYNTH_NET_INTERFACES=(${SYNTH_NET_INTERFACES[@]/$iface_ignore/})
if [ ${#SYNTH_NET_INTERFACES[@]} -eq 0 ]; then
    LogErr "The only synthetic interface is the one which LIS uses to send files/commands to the VM."
    SetTestStateAborted
    exit 0
fi
test_iface=${SYNTH_NET_INTERFACES[*]}
LogMsg "Found ${#SYNTH_NET_INTERFACES[@]} synthetic interface(s): $test_iface in VM"
ip link show $test_iface >/dev/null 2>&1
if [ 0 -ne $? ]; then
    LogErr "Invalid synthetic interface $test_iface"
    SetTestStateFailed
    exit 0
fi

# Set static ip
CreateIfupConfigFile "$test_iface" "static" "$STATIC_IP" "$NETMASK"
# if failed to assigned address
if [ 0 -ne $? ]; then
    LogErr "Failed to assign static ip $STATIC_IP netmask $NETMASK on interface $test_iface"
    SetTestStateFailed
    exit 0
fi
ip link show $test_iface

# get file size in bytes
if [ "${FILE_SIZE_GB:-UNDEFINED}" = "UNDEFINED" ]; then
    file_size=$((10*1024*1024*1024))                      # 10 GB
else
    file_size=$((FILE_SIZE_GB*1024*1024*1024))
fi

LogMsg "Checking for local disk space"
total_space=$((file_size*2))
LogMsg "Total disk space needed - $total_space"
# Check disk size on local vm
IsFreeSpace "$tmp" "$total_space"
if [ 0 -ne $? ]; then
    LogMsg "Not enough free space on current partition to create the test file"
    SetTestStateFailed
    exit 0
fi

LogMsg "Enough free space locally to create the file"
LogMsg "Checking for disk space on $STATIC_IP2"
# Check disk size on remote vm. Cannot use IsFreeSpace function directly. Need to export utils.sh to the remote_vm, source it and then access the functions therein
scp -i "$homeDir"/.ssh/"$SSH_PRIVATE_KEY" -o StrictHostKeyChecking=no utils.sh "$remote_user"@"$STATIC_IP2":/tmp
if [ 0 -ne $? ]; then
    LogErr "Cannot copy utils.sh to $STATIC_IP2:/tmp"
    SetTestStateFailed
    exit 0
fi

ssh -i "$homeDir"/.ssh/"$SSH_PRIVATE_KEY" -o StrictHostKeyChecking=no "$remote_user"@"$STATIC_IP2" "
    . /tmp/utils.sh
    IsFreeSpace $tmp $total_space
    if [ 0 -ne \$? ]; then
        exit 1
    fi
    echo $tmp
    exit 0
    "
sts=$?

if [ 1 -eq $sts ]; then
    LogErr "Not enough free space on $STATIC_IP2 to create the test file"
    SetTestStateFailed
    exit 0
fi
if [ 0 -ne $sts ]; then
    LogErr "Unable to connect through ssh to $STATIC_IP2"
    SetTestStateFailed
    exit 0
fi
LogMsg "Enough free space remotely to create the file"

# get source to create the file
if [ "${ZERO_FILE:-UNDEFINED}" = "UNDEFINED" ]; then
    file_source=/dev/urandom
else
    file_source=/dev/zero
fi

# create file locally with PID appended
output_file_1=large_file_1_$$
output_file_2=large_file_2_$$

if [ -d "$tmp"/"$output_file_1" ]; then
    rm -rf "$tmp"/"$output_file_1"
fi

if [ -e "$tmp"/"$output_file_1" ]; then
    rm -f "$tmp"/"$output_file_1"
fi

#disabling firewall on both VMs
iptables -F
ssh -i "$homeDir"/.ssh/"$SSH_PRIVATE_KEY" -o StrictHostKeyChecking=no "$remote_user"@"$STATIC_IP2" "iptables -F"

dd if=$file_source of="$tmp"/"$output_file_1" bs=1M count=$((file_size/1024/1024))
if [ 0 -ne $? ]; then
    LogErr "Unable to create file $output_file_1 in $tmp"
    SetTestStateFailed
    exit 0
fi

LogMsg "Successfully created $output_file"
ssh -i "$homeDir"/.ssh/"$SSH_PRIVATE_KEY" -o StrictHostKeyChecking=no "$remote_user"@"$STATIC_IP2" "dd if=${file_source} of=${tmp}/${output_file_2} bs=1M count=$((file_size/1024/1024))"
if [ 0 -ne $? ]; then
    LogErr "Unable to create file $output_file_2 in $tmp"
    SetTestStateFailed
    exit 0
fi

#compute md5sum
local_md5sum_file_1=$(md5sum ${tmp}/${output_file_1} | cut -f 1 -d ' ')
remote_md5sum_file_2=$(ssh -i "$homeDir"/.ssh/"$SSH_PRIVATE_KEY" -o StrictHostKeyChecking=no "$remote_user"@"$STATIC_IP2" "md5sum ${tmp}/${output_file_2} |  cut -f 1 -d ' '")
#send file to remote_vm
remote_exit_status_file_path="${tmp}/exit_status"
LogMsg "Remote exit status: ${remote_exit_status_file_path} "
remote_cmd="
    scp -i ${HOME}/.ssh/${SSH_PRIVATE_KEY} -o StrictHostKeyChecking=no ${tmp}/${output_file_2} ${remote_user}@${ipv4}:${tmp}/${output_file_2};echo \$? > ${remote_exit_status_file_path}
"
ssh -i "$homeDir"/.ssh/"$SSH_PRIVATE_KEY" -o StrictHostKeyChecking=no "$remote_user"@"$STATIC_IP2" "echo '${remote_cmd}' > send_file.sh"
ssh -i "$homeDir"/.ssh/"$SSH_PRIVATE_KEY" -o StrictHostKeyChecking=no "$remote_user"@"$STATIC_IP2" "setsid bash send_file.sh >/dev/null 2>&1 < /dev/null &"
scp -i "$homeDir"/.ssh/"$SSH_PRIVATE_KEY" -o StrictHostKeyChecking=no "$tmp"/"$output_file_1" "$remote_user"@"$STATIC_IP2":"$tmp"/"$output_file_1"
if [ 0 -ne $? ]; then
    LogErr "Unable to copy file $output_file_1 to $STATIC_IP2:$tmp/$output_file_1"
    SetTestStateFailed
    exit 0
fi
LogMsg "Successfully sent $output_file_1 to $STATIC_IP2:${tmp}/$output_file_1"

remote_exit_status=$(ssh -i "$homeDir"/.ssh/"$SSH_PRIVATE_KEY" -o StrictHostKeyChecking=no "$remote_user"@"$STATIC_IP2" "cat ${remote_exit_status_file_path}")
if [ "$remote_exit_status" -ne 0 ]; then
    LogErr "Unable to copy file $output_file_2 to $ipv4:${tmp}/${output_file_2}"
    SetTestStateFailed
    exit 0
fi
LogMsg "STATUS: $remote_exit_status"

# save md5sumes of copied files
remote_md5sum_file_1=$(ssh -i "$homeDir"/.ssh/"$SSH_PRIVATE_KEY" -o StrictHostKeyChecking=no "$remote_user"@"$STATIC_IP2" "md5sum ${tmp}/${output_file_1} | cut -f 1 -d ' '")
local_md5sum_file_2=$(md5sum ${tmp}/${output_file_2} | cut -f 1 -d ' ')

# delete files
rm -f "$tmp"/$output_file_1
rm -f "$tmp"/$output_file_2
ssh -i "$homeDir"/.ssh/"$SSH_PRIVATE_KEY" -o StrictHostKeyChecking=no "$remote_user"@"$STATIC_IP2" "rm -f ${tmp}/${output_file_1}"
ssh -i "$homeDir"/.ssh/"$SSH_PRIVATE_KEY" -o StrictHostKeyChecking=no "$remote_user"@"$STATIC_IP2" "rm -f ${tmp}/${output_file_2}"
if [ "$local_md5sum_file_1" != "$remote_md5sum_file_1" ]; then
    LogErr "md5sums differ for ${output_file_1}. Files do not match: ${local_md5sum_file_1} - ${remote_md5sum_file_1}"
    SetTestStateFailed
    exit 0
fi

if [ "$local_md5sum_file_2" != "$remote_md5sum_file_2" ]; then
    LogMsg "md5sums differ for ${output_file_2}. Files do not match: ${local_md5sum_file_2} - ${remote_md5sum_file_2}"
    SetTestStateFailed
    exit 0
fi
LogMsg "Checksums of files match. Updating test case state to completed"
SetTestStateCompleted
exit 0