#!/bin/bash

# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

# Description:
#   This script verifies that the network doesn't
#   lose connection by copying a large file(~1GB)file
#   between two VM's when MTU is set to 9000 on the network
#   adapters.
#
#############################################################################################################
remote_user="root"
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

# Check for expect. If it's not on the system, install it
expect -v
if [ $? -ne 0 ]; then
    update_repos
    if [ $? -ne 0 ]; then
        LogErr "Could not update repos"
        SetTestStateAborted 
        exit 0
    fi

    install_package "expect"
    if [ $? -ne 0 ]; then
        LogErr "Could not install expect"
        SetTestStateAborted 
        exit 0
    fi
fi

# Get file size in bytes
if [ "${FILE_SIZE_GB:-UNDEFINED}" = "UNDEFINED" ]; then
    file_size=$((1024*1024*1024))
else
    file_size=$((FILE_SIZE_GB*1024*1024*1024))
fi

# Check disk size on local vm
IsFreeSpace "$HOME" "$file_size"
if [ 0 -ne $? ]; then
    LogMsg "Not enough free space on current partition to create the test file"
    SetTestStateFailed
    exit 0
fi
LogMsg "Enough free space locally to create the file"

# Check disk size on remote vm. Cannot use IsFreeSpace function directly. Need to export utils.sh to the remote_vm, source it and then access the functions therein
LogMsg "Checking for disk space on $STATIC_IP2"
scp -i "$HOME"/.ssh/"$SSH_PRIVATE_KEY" -o StrictHostKeyChecking=no utils.sh "$remote_user"@"$STATIC_IP2":/tmp
if [ 0 -ne $? ]; then
    LogMsg "Cannot copy utils.sh to $STATIC_IP2:/tmp"
    SetTestStateFailed
    exit 0
fi

remote_home=$(ssh -i "$HOME"/.ssh/"$SSH_PRIVATE_KEY" -o StrictHostKeyChecking=no "$remote_user"@"$STATIC_IP2" "
    . /tmp/utils.sh
    IsFreeSpace \"\$HOME\" $file_size
    if [ 0 -ne \$? ]; then
        exit 0
    fi
    echo \"\$HOME\"
    exit 0
    ")

# Get ssh status
sts=$?
if [ 1 -eq $sts ]; then
    LogMsg "Not enough free space on $STATIC_IP2 to create the test file"
    SetTestStateFailed
    exit 0
fi
if [ 0 -ne $sts ]; then
    LogMsg "Unable to connect through ssh to $STATIC_IP2"
    SetTestStateFailed
    exit 0
fi
LogMsg "Enough free space remotely to create the file"

# Get source to create the file
if [ "${ZERO_FILE:-UNDEFINED}" = "UNDEFINED" ]; then
    file_source=/dev/urandom
else
    file_source=/dev/zero
fi

# Create file locally with PID appended
output_file=large_file_$$
if [ -d "$HOME"/"$output_file" ]; then
    rm -rf "$HOME"/"$output_file"
fi
if [ -e "$HOME"/"$output_file" ]; then
    rm -f "$HOME"/"$output_file"
fi

dd if=$file_source of="$HOME"/"$output_file" bs=1M count=$((file_size/1024/1024))

if [ 0 -ne $? ]; then
    LogMsg "Unable to create file $output_file in $HOME"
    SetTestStateFailed
    exit 0
fi

LogMsg "Successfully created $output_file"

# Compute md5sum
local_md5sum=$(md5sum $output_file | cut -f 1 -d ' ')

# try to set mtu to 65536
# save the maximum capable mtu
change_mtu_increment $test_iface $iface_ignore
if [ $? -ne 0 ]; then
    LogErr "Failed to change MTU on $test_iface"
    SetTestStateFailed
    exit 0
fi

# If SSH_PRIVATE_KEY was specified, ssh into the STATIC_IP2 and set the MTU of all interfaces to $max_mtu
# If not, assume that it was already set.
LogMsg "Setting all interfaces on $STATIC_IP2 mtu to $max_mtu"
ssh -i "$HOME"/.ssh/"$SSH_PRIVATE_KEY" -o StrictHostKeyChecking=no "$remote_user"@"$STATIC_IP2" "
    remote_interface=\$(ip -o addr show | grep \"$STATIC_IP2\" | cut -d ' ' -f2)
    if [ x\"\$remote_interface\" = x ]; then
        exit 1
    fi
    # make sure no legacy interfaces are present
    legacy_interface_no=\$(find /sys/devices -name net -a ! -ipath '*vmbus*' -a ! -path '*virtual*' -a ! -path '*lo*' | wc -l)

    if [ 0 -ne \"\$legacy_interface_no\" ]; then
        exit 2
    fi
    ip link set dev \$remote_interface mtu \"$max_mtu\"
    if [ 0 -ne \$? ]; then
        exit 2
    fi
    remote_actual_mtu=\$(ip -o link show \"\$remote_interface\" | cut -d ' ' -f5)
    if [ x\"\$remote_actual_mtu\" !=  x\"$max_mtu\" ]; then
        exit 3
    fi
    exit 0
"
if [ 0 -ne $? ]; then
    LogErr "Unable to set $STATIC_IP2 mtu to $max_mtu"
    SetTestStateFailed
    exit 0
fi

# Send file to remote_vm
expect -c "
    spawn scp -i "$HOME"/.ssh/"$SSH_PRIVATE_KEY" "$output_file" "$remote_user"@"$STATIC_IP2":"$remote_home"/"$output_file"
    expect -timeout -1 \"stalled\" {close}
    interact
" > expect.log
 if grep -q stalled "expect.log"; then
    LogErr "File copy stalled!"
    SetTestStateFailed
    exit 0
 fi
LogMsg "Successfully sent $output_file to $STATIC_IP2:$remote_home/$output_file"

# Compute md5sum of remote file
remote_md5sum=$(ssh -i "$HOME"/.ssh/"$SSH_PRIVATE_KEY" -o StrictHostKeyChecking=no "$remote_user"@"$STATIC_IP2" md5sum $output_file | cut -f 1 -d ' ')
if [ "$local_md5sum" != "$remote_md5sum" ]; then
    [ $NO_DELETE -eq 0 ] && rm -f "$HOME"/$output_file
    LogErr "md5sums differ. Files do not match"
    SetTestStateFailed
    exit 0
fi
# Erase file locally, if set
[ $NO_DELETE -eq 0 ] && rm -f $output_file

LogMsg "md5sums are matching. Updating test case state to completed"
SetTestStateCompleted
exit 0