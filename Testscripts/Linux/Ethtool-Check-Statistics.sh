#!/bin/bash

# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

#############################################################################
# Ethtool-Check-Statistics.sh
# Description:
#       1. Add new Private NIC and set static IP for test interface.
#       2. Check for ethtool and netperf.
#       3. Start first test on 'tx_send_full' param with netperf TCP_SENDFILE.
#       4. Start the second test on 'wake_queue' param with changing mtu for 10 times.
#       5. Check if results are as expected.
#############################################################################
remote_user="root"
remote_user_home="/root"

SendFile(){
    # Download netperf 2.7.0
    homeDir="/home/${SUDO_USER}"
    cd ${homeDir}
    wget https://github.com/HewlettPackard/netperf/archive/netperf-2.7.0.tar.gz > /dev/null 2>&1
    if [ $? -ne 0 ]; then
        LogErr "Unable to download netperf."
        return 1
    fi
    tar -xvf netperf-2.7.0.tar.gz > /dev/null 2>&1

    # Get the root directory of the tarball
    downloadDir="/netperf-netperf-2.7.0"
    rootDir="${homeDir}/$downloadDir"
    pushd ${rootDir}

    # Distro specific setup
    GetDistro

    case "$DISTRO" in
    debian*|ubuntu*)
        service ufw status
        if [ $? -ne 3 ]; then
            LogMsg "Disabling firewall on Ubuntu.."
            iptables -t filter -F
            if [ $? -ne 0 ]; then
                LogErr "Failed to stop ufw."
                return 1
            fi
            iptables -t nat -F
            if [ $? -ne 0 ]; then
                LogErr "Failed to stop ufw."
                return 1
            fi
        fi;;
    redhat_5|redhat_6)
        LogMsg "Check iptables status on RHEL."
        service iptables status
        if [ $? -ne 3 ]; then
            LogMsg "Disabling firewall on Redhat.."
            iptables -t filter -F
            if [ $? -ne 0 ]; then
                LogErr "Failed to flush iptables rules."
                return 1
            fi
            iptables -t nat -F
            if [ $? -ne 0 ]; then
                LogErr "Failed to flush iptables nat rules."
                return 1
            fi
            ip6tables -t filter -F
            if [ $? -ne 0 ]; then
                LogErr "Failed to flush ip6tables rules."
                return 1
            fi
            ip6tables -t nat -F
            if [ $? -ne 0 ]; then
                LogErr "Failed to flush ip6tables nat rules."
                return 1
            fi
        fi;;
    redhat_7)
        LogMsg "Check iptables status on RHEL."
        systemctl status firewalld
        if [ $? -ne 3 ]; then
            LogMsg "Disabling firewall on Redhat 7.."
            systemctl disable firewalld
            if [ $? -ne 0 ]; then
                LogErr "Failed to stop firewalld."
                return 1
            fi
            systemctl stop firewalld
            if [ $? -ne 0 ]; then
                LogErr "Failed to turn off firewalld."
                return 1
            fi
        fi
        LogMsg "Check iptables status on RHEL 7."
        service iptables status
        if [ $? -ne 3 ]; then
            iptables -t filter -F
            if [ $? -ne 0 ]; then
                LogErr "Failed to flush iptables rules."
                return 1
            fi
            iptables -t nat -F
            if [ $? -ne 0 ]; then
                LogErr "Failed to flush iptables nat rules."
                return 1
            fi
            ip6tables -t filter -F
            if [ $? -ne 0 ]; then
                LogErr "Failed to flush ip6tables rules."
                return 1
            fi
            ip6tables -t nat -F
            if [ $? -ne 0 ]; then
                LogErr "Failed to flush ip6tables nat rules."
                return 1
            fi
        fi;;
    suse_12)
        LogMsg "Check iptables status on SLES."
        service SuSEfirewall2 status
        if [ $? -ne 3 ]; then
            iptables -F;
            if [ $? -ne 0 ]; then
                LogErr "Failed to flush iptables rules."
                return 1
            fi
            service SuSEfirewall2 stop
            if [ $? -ne 0 ]; then
                LogErr "Failed to stop iptables."
                return 1
            fi
            chkconfig SuSEfirewall2 off
            if [ $? -ne 0 ]; then
                LogErr "Failed to turn off iptables."
                return 1
            fi
            iptables -t filter -F
            iptables -t nat -F
        fi;;
        mariner)
            install_package "make kernel-headers binutils glibc-devel zlib-devel"
        ;;
    esac
    ./configure > /dev/null 2>&1
    if [ $? -ne 0 ]; then
        LogErr "Unable to configure make file for netperf."
        return 1
    fi

    make > /dev/null 2>&1
    if [ $? -ne 0 ]; then
        LogErr "Unable to build netperf."
        return 1
    fi

    make install > /dev/null 2>&1
    if [ $? -ne 0 ]; then
        LogErr "Unable to install netperf."
        return 1
    fi
    export PATH="/usr/local/bin:${PATH}"
    popd
    LogMsg "Copy files to dependency vm: ${STATIC_IP2}"
    scp -i "$homeDir"/.ssh/"$SSH_PRIVATE_KEY" -o StrictHostKeyChecking=no ${homeDir}/NET-Netperf-Server.sh \
        ${remote_user}@[${STATIC_IP2}]: > /dev/null 2>&1
    if [ $? -ne 0 ]; then
        LogErr "Unable to copy test scripts to dependency VM: ${STATIC_IP2}. scp command failed."
        return 1
    fi
    scp -i "$homeDir"/.ssh/"$SSH_PRIVATE_KEY" -o StrictHostKeyChecking=no ${homeDir}/constants.sh \
        ${remote_user}@[${STATIC_IP2}]: > /dev/null 2>&1
    scp -i "$homeDir"/.ssh/"$SSH_PRIVATE_KEY" -o StrictHostKeyChecking=no ${homeDir}/net_constants.sh \
        ${remote_user}@[${STATIC_IP2}]: > /dev/null 2>&1
    scp -i "$homeDir"/.ssh/"$SSH_PRIVATE_KEY" -o StrictHostKeyChecking=no ${homeDir}/utils.sh \
        ${remote_user}@[${STATIC_IP2}]: > /dev/null 2>&1

    #Start netperf in server mode on the dependency vm
    LogMsg "Starting netperf in server mode on ${STATIC_IP2}"
    ssh -i "$homeDir"/.ssh/"$SSH_PRIVATE_KEY" -o StrictHostKeyChecking=no ${remote_user}@${STATIC_IP2} \
        "echo '${remote_user_home}/NET-Netperf-Server.sh > netperf_ServerScript.log' | at now" > /dev/null 2>&1
    if [ $? -ne 0 ]; then
        LogErr "Unable to start netperf server script on the dependency vm."
        return 1
    fi

    # Wait for server to be ready
    wait_for_server=600
    server_state_file=serverstate.txt
    while [ $wait_for_server -gt 0 ]; do
        # Try to copy and understand server state
        scp -i "$homeDir"/.ssh/"$SSH_PRIVATE_KEY" -o StrictHostKeyChecking=no \
        ${remote_user}@[${STATIC_IP2}]:${remote_user_home}/state.txt ${homeDir}/${server_state_file} > /dev/null 2>&1

        if [ -f ${homeDir}/${server_state_file} ]; then
            server_state=$(head -n 1 ${homeDir}/${server_state_file})
            if [ "$server_state" == "netperfRunning" ]; then
                break
            elif [[ "$server_state" == "TestFailed" || "$server_state" == "TestAborted" ]]; then
                LogMsg "Running NET-Netperf-Server.sh was aborted or failed on dependency vm:$server_state"
                return 1
            elif [ "$server_state" == "TestRunning" ]; then
                continue
            fi
        fi
        sleep 5
        wait_for_server=$(($wait_for_server - 5))
    done

    if [ $wait_for_server -eq 0 ]; then
        LogErr "netperf server script has been triggered but is not in running state within ${wait_for_server} seconds."
        return 1
    else
        LogMsg "SUCCESS: Netperf server is ready."
    fi

    # create 4GB file test for TCP_SENDFILE test
    LogMsg "Create file under folder $PWD"
    dd if=/dev/zero of=test1 bs=1M count=4096

    LogMsg "Starting netperf .."
    netperf=$(find / -name netperf | grep bin | tail -1)
    $netperf -H ${STATIC_IP2} -F test1 -t TCP_SENDFILE -l 300 -- -m 1 & > netperf.log 2>&1
    if [ $? -ne 0 ]; then
        LogErr "Unable to run netperf on VM."
        return 1
    fi
    sleep 310

    # Get the modified value of 'tx_send_full' param after netpef test
    new_send_value=$(ethtool -S $test_iface | grep "tx_send_full" | cut -d ":" -f 2)

    # LogMsg values
    LogMsg "Kernel: $(uname -r)."
    LogMsg "Tx_send_full before netperf test: $send_value."
    LogMsg "Tx_send_full after netperf test: $new_send_value."
    # Check results
    if [ $new_send_value -gt 10 ]; then
        LogMsg "Successfully test on tx_send_full param."
        return 0
    else
        LogErr "test on tx_send_full param failed."
        return 1
    fi
}

ChangeMTU(){
    # try to set mtu to 65536
    # save the maximum capable mtu
    change_mtu_increment $test_iface $iface_ignore
    if [ $? -ne 0 ]; then
        LogErr "Failed to change MTU on $test_iface"
        SetTestStateFailed
        exit 0
    fi

    #Get the value of 'wake_queue' after changing MTU
    new_wake_value=$(ethtool -S $test_iface | grep "wake_queue" | cut -d ":" -f 2)

    #Log the values
    LogMsg "Wake_queue start value: $wake_value"
    LogMsg "Wake_queue value after changing MTU: $new_wake_value"
}

# Main script body
. net_constants.sh || {
    echo "unable to source net_constants.sh!"
    echo "TestAborted" > state.txt
    exit 0
}
# Source utils.sh
. utils.sh || {
    echo "unable to source utils.sh!"
    echo "TestAborted" > state.txt
    exit 0
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
    msg="The test parameter NETMASK is not defined in constants file . Defaulting to 255.255.255.0"
    LogMsg "$msg"
    NETMASK=255.255.255.0
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

# Install the dependencies
update_repos
install_package "wget make gcc"

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
# Check ethtool
ethtool --version
if [ $? -ne 0 ]; then
    update_repos
    install_package "ethtool"
fi

# Check if Statistics from ethtool are available
sts=$(ethtool -S $test_iface 2>&1)
if [[ $sts = *"no stats available"* ]]; then
    LogErr "$sts"
    LogErr "Operation not supported. Test Skipped."
    SetTestStateAborted
    exit 0
fi

# Make all bash scripts executable
cd ${homeDir}

#Start the first test on tx_send_full param with TCP_SENDFILE netperf
#Get the started value of 'tx_send_full' param from statistics if exist and if not skip the test.
send_value=$(ethtool -S $test_iface | grep "tx_send_full" | cut -d ":" -f 2)
if [ -n "$send_value" ]; then
    SendFile
    sts_sendfile=$?
else
    LogMsg "SendFile test is Skipped!'Tx_send_full' param not found."
    sts_sendfile=2
fi

#Start the second test - on wake_queue param
#Get the started value of 'wake_queue' param from statistics if exist and if not skip the test.
wake_value=$(ethtool -S $test_iface | grep "wake_queue" | cut -d ":" -f 2)
if [ -n "$wake_value" ];then
    ChangeMTU
    sts_changemtu=$?
else
    LogMsg "ChangeMTU test is Skipped!'Wake_queue' param not found."
    sts_changemtu=2
fi

# Get logs from dependency vm
scp -i "$homeDir"/.ssh/"$SSH_PRIVATE_KEY" -o StrictHostKeyChecking=no -r \
${remote_user}@[${STATIC_IP2}]:${remote_user_home}/netperf_ServerScript.log ${homeDir}/netperf_ServerScript.log

# Shutdown dependency VM
ssh -i "$homeDir"/.ssh/"$SSH_PRIVATE_KEY" -o StrictHostKeyChecking=no ${remote_user}@${STATIC_IP2} "init 0" &

if [[ $sts_sendfile -eq 1 || $sts_changemtu -eq 1 ]];then
    SetTestStateFailed
    exit 0
elif [[ $sts_sendfile -eq 2 && $sts_changemtu -eq 2 ]];then
    SetTestStateAborted
    exit 0
fi

# If we made it here, everything worked
LogMsg "Test completed successfully"
SetTestStateCompleted
exit 0
