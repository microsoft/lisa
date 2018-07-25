#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

#Reference:  https://docs.microsoft.com/en-us/azure/virtual-network/virtual-network-create-vm-accelerated-networking
bootLogs=`dmesg`
if [[ $bootLogs =~ "Data path switched to VF" ]];
then
	echo "DATAPATH_SWITCHED_TO_VF"
else
	wget https://raw.githubusercontent.com/torvalds/linux/master/tools/hv/bondvf.sh
	chmod +x ./bondvf.sh
	./bondvf.sh
	cp bondvf.sh /etc/init.d
	update-rc.d bondvf.sh defaults
	echo "SYSTEM_RESTART_REQUIRED"
fi
exit 0