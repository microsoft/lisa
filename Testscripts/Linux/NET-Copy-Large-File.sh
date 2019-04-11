#!/bin/bash

# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

#############################################################################################################
#
# Description:
#   This script verifies that the network doesn't lose connection
#   by copying a large file(~10GB)file between two VM's with IC installed.
#
#   Steps:
#   1. Verify configuration file constants.sh
#   2. Verify ssh private key file for remote VM was given
#   4. Verify there is enough local disk space for 10GB file
#   5. Verify there is enough remote disk space for 10GB file
#   6. Create 10GB file from /dev/urandom. Save md5sum of it and copy it from local VM to remote VM using scp
#   7. Erase local file after copy finished
#   8. Copy data back from repository server to the local VM using scp
#   9. Erase remote file after copy finished
#   9. Make new md5sum of received file and compare to the one calculated earlier
#############################################################################################################
remote_user=$(whoami)
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
if [ "${NETMASK:-UNDEFINED}" = "UNDEFINED" ]; then
    LogMsg "The test parameter NETMASK is not defined in constants file . Defaulting to 255.255.255.0"
    NETMASK=255.255.255.0
fi
if [ "$ADDRESS_FAMILY" = "IPv6" ];then
    scp_cmd="scp -6"
    ssh_cmd="ssh -6"
    ip_cmd="$remote_user"@"[${STATIC_IP2}]"
else
    scp_cmd="scp"
    ssh_cmd="ssh"
    ip_cmd="$remote_user"@"${STATIC_IP2}"
fi
if [ "${NO_DELETE:-UNDEFINED}" = "UNDEFINED" ]; then
    LogMsg "The test parameter NO_DELETE is not defined in ${__LIS_CONSTANTS_FILE} . Generated file will be deleted"
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

# Check disk size on local vm
LogMsg "Checking for local disk space"
IsFreeSpace "/home/${SUDO_USER}" "$file_size"
if [ 0 -ne $? ]; then
    LogErr "Not enough free space on current partition to create the test file"
    SetTestStateFailed
    exit 0
fi
LogMsg "Enough free space locally to create the file"

LogMsg "Checking for disk space on $STATIC_IP2"
# Check disk size on remote vm. Cannot use IsFreeSpace function directly. Need to export utils.sh to the remote_vm, source it and then access the functions therein
$scp_cmd -i "/home/${SUDO_USER}"/.ssh/"$SSH_PRIVATE_KEY" -o StrictHostKeyChecking=no utils.sh $ip_cmd:/tmp
if [ 0 -ne $? ]; then
    LogErr "Cannot copy utils.sh to $STATIC_IP2:/tmp"
    SetTestStateFailed
    exit 0
fi

remote_home=$($ssh_cmd -i "/home/${SUDO_USER}"/.ssh/"$SSH_PRIVATE_KEY" -o StrictHostKeyChecking=no "$remote_user"@"$STATIC_IP2" "
    . /tmp/utils.sh
    IsFreeSpace \"\$HOME\" $file_size
    if [ 0 -ne \$? ]; then
        exit 0
    fi
    echo \"\$HOME\"
    exit 0
    ")

# get ssh status
sts=$?

if [ 1 -eq $sts ]; then
    LogErr "Not enough free space on $STATIC_IP2 to create the test file"
    SetTestStateFailed
    exit 0
fi

# if status is neither 1, nor 0 then ssh encountered an error
if [ 0 -ne $sts ]; then
    LogErr "Unable to connect through ssh to $STATIC_IP2"
    SetTestStateFailed
    exit 0
fi
LogMsg "Enough free space remotely to create the file"

if [ "${ZERO_FILE:-UNDEFINED}" = "UNDEFINED" ]; then
    file_source=/dev/urandom
else
    file_source=/dev/zero
fi
# create file locally with PID appended
output_file=large_file_$$
if [ -d "/home/${SUDO_USER}"/"$output_file" ]; then
    rm -rf "/home/${SUDO_USER}"/"$output_file"
fi

if [ -e "/home/${SUDO_USER}"/"$output_file" ]; then
    rm -f "/home/${SUDO_USER}"/"$output_file"
fi

dd if=$file_source of="/home/${SUDO_USER}"/"$output_file" bs=1M count=$((file_size/1024/1024))
if [ 0 -ne $? ]; then
    LogErr "Unable to create file $output_file in $HOME"
    SetTestStateFailed
    exit 0
fi
LogMsg "Successfully created $output_file"

# compute md5sum
local_md5sum=$(md5sum $output_file | cut -f 1 -d ' ')

# send file to remote_vm
$scp_cmd -i "/home/${SUDO_USER}"/.ssh/"$SSH_PRIVATE_KEY" -o StrictHostKeyChecking=no "$output_file" $ip_cmd:"$remote_home"/"$output_file"
if [ 0 -ne $? ]; then
    [ $NO_DELETE -eq 0 ] && rm -f "/home/${SUDO_USER}"/$output_file
    LogErr "Unable to copy file $output_file to $STATIC_IP2:$remote_home/$output_file"
    SetTestStateFailed
    exit 0
fi
LogMsg "Successfully sent $output_file to $STATIC_IP2:$remote_home/$output_file"

# erase file locally, if set
[ $NO_DELETE -eq 0 ] && rm -f $output_file

# copy file back from remote vm
$scp_cmd -i "/home/${SUDO_USER}"/.ssh/"$SSH_PRIVATE_KEY" -o StrictHostKeyChecking=no $ip_cmd:"$remote_home"/"$output_file" "/home/${SUDO_USER}"/"$output_file"
if [ 0 -ne $? ]; then
    #try to erase file from remote vm
    [ $NO_DELETE -eq 0 ] && $ssh_cmd -i "/home/${SUDO_USER}"/.ssh/"$SSH_PRIVATE_KEY" -o StrictHostKeyChecking=no "$remote_user"@"$STATIC_IP2" "rm -f \$HOME/$output_file"
    LogErr "Unable to copy from $STATIC_IP2:$remote_home/$output_file"
    SetTestStateFailed
    exit 0
fi
LogMsg "Received $output_file from $STATIC_IP2"

# delete remote file
[ $NO_DELETE -eq 0 ] && $ssh_cmd -i "/home/${SUDO_USER}"/.ssh/"$SSH_PRIVATE_KEY" -o StrictHostKeyChecking=no "$remote_user"@"$STATIC_IP2" "rm -f $remote_home/$output_file"

# check md5sums
remote_md5sum=$(md5sum $output_file | cut -f 1 -d ' ')

if [ "$local_md5sum" != "$remote_md5sum" ]; then
    [ $NO_DELETE -eq 0 ] && rm -f "/home/${SUDO_USER}"/$output_file
    LogErr "md5sums differ. Files do not match"
    SetTestStateFailed
    exit 0
fi

# delete local file again
[ $NO_DELETE -eq 0 ] && rm -f "/home/${SUDO_USER}"/$output_file

LogMsg "Updating test case state to completed"
SetTestStateCompleted
exit 0