#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

# This script holds commons function used in XDP Testcases

function get_vf_name() {
	local nicName=$1
	local ignoreIF=$(ip route | grep default | awk '{print $5}')
        local interfaces=$(ls /sys/class/net | grep -v lo | grep -v ${ignoreIF})
        local synthIFs=""
        local vfIFs=""
        local interface
        for interface in ${interfaces}; do
                # alternative is, but then must always know driver name
                # readlink -f /sys/class/net/<interface>/device/driver/
                local bus_addr=$(ethtool -i ${interface} | grep bus-info | awk '{print $2}')
                if [ -z "${bus_addr}" ]; then
                        synthIFs="${synthIFs} ${interface}"
                else
                        vfIFs="${vfIFs} ${interface}"
                fi
        done

        local vfIF
        local synthMAC=$(ip link show $nicName | grep ether | awk '{print $2}')
        for vfIF in ${vfIFs}; do
                local vfMAC=$(ip link show ${vfIF} | grep ether | awk '{print $2}')
                # single = is posix compliant
                if [ "${synthMAC}" = "${vfMAC}" ]; then
                        echo "${vfIF}"
                        break
                fi
        done
}

function calculate_packets_drop(){
	local nicName=$1
        local vfName=$(get_vf_name ${nicName})
        local synthDrop=0
        IFS=$'\n' read -r -d '' -a xdp_packet_array < <(ethtool -S $nicName | grep 'xdp' | cut -d':' -f2)
        for i in "${xdp_packet_array[@]}";
        do
                synthDrop=$((synthDrop+i))
        done
        vfDrop=$(ethtool -S $vfName | grep rx_xdp_drop | cut -d':' -f2)
        if [ $? -ne 0 ]; then
                echo "$((synthDrop))"
        else
                echo "$((vfDrop + synthDrop))"
        fi
}

function calculate_packets_forward(){
	local nicName=$1
	local vfName=$(get_vf_name ${nicName})
	vfForward=$(ethtool -S $vfName | grep rx_xdp_tx_xmit | cut -d':' -f2)
	echo "$((vfForward))"
}
