#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
# Description : Enables passwordless authentication for root user.
# How to use : ./enablePasswordLessRoot.sh
# In multi VM cluster. Execute this script in one VM. It will create a sshFix.tar
# Copy this sshFix.tar to other VMs (/root) in your cluster and execute same script. It will extract previously created keys.
# This way, all VMs will have same public and private keys in .ssh folder.

rm -rf /root/.ssh
cd /root
keyTarFile=sshFix.tar
if [ -e ${keyTarFile} ]; then
	echo | ssh-keygen -N ''
	rm -rf .ssh/*
	tar -xvf ${keyTarFile}
	echo "KEY_COPIED_SUCCESSFULLY"
else
	echo | ssh-keygen -N ''
	cat /root/.ssh/id_rsa.pub > /root/.ssh/authorized_keys
	echo "Host *" > /root/.ssh/config
	echo "StrictHostKeyChecking no" >> /root/.ssh/config
	rm -rf /root/.ssh/known_hosts
	cd /root/ && tar -cvf sshFix.tar .ssh/*
	echo "KEY_GENERATED_SUCCESSFULLY"
fi
