#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
# Description : Enables passwordless authentication for root user.
# How to use : ./enable_passwordless_root.sh
# In multi VM cluster. Execute this script in one VM. It will create a sshFix.tar
# Copy this sshFix.tar to other VMs (/root) in your cluster and execute same script. It will extract previously created keys.
# This way, all VMs will have same public and private keys in .ssh folder.
set -xe

if [[ $1 != '' ]]; then
    Custom_Path=$1
else
    echo "Using default path /root..."
    Custom_Path="/root"
fi

rm -rf /root/.ssh/id_rsa*
cd /root
keyTarFile=sshFix.tar
if [ -e "${Custom_Path}/${keyTarFile}" ]; then
    tarPath="${Custom_Path}/${keyTarFile}"
    echo | ssh-keygen -N ''
    rm -rf .ssh/*
    if [ -e ${tarPath} ]; then
        tar -xvf ${tarPath}
    else
        tar -xvf ${keyTarFile}
    fi
    echo "KEY_COPIED_SUCCESSFULLY"
else
    authorized_keys_content=""
    if [ -f /root/.ssh/authorized_keys ]; then
        authorized_keys_content=$(cat /root/.ssh/authorized_keys)
    fi
    if [[ "${authorized_keys_content}" != "" ]]; then
        if [[ "${authorized_keys_content}" =~ "Please login as the user" ]]; then
            echo "${authorized_keys_content}" > authorized_keys
            content="$(cat authorized_keys)"
            IFS=' ' read -r -a array <<< "$content"
            echo "${array[@]: -2:2}" > authorized_keys
            cp authorized_keys /root/.ssh/authorized_keys
            rm -rf authorized_keys
        fi
    fi
    echo | ssh-keygen -N ''
    cat /root/.ssh/id_rsa.pub >> /root/.ssh/authorized_keys
    echo "Host *" > /root/.ssh/config
    echo "StrictHostKeyChecking no" >> /root/.ssh/config
    rm -rf /root/.ssh/known_hosts
    if [ -e ${Custom_Path} ]; then
        cd /root/ && tar -cvf ${keyTarFile} .ssh/*
        mv ${keyTarFile} ${Custom_Path} || true
    else
        cd /root/ && tar -cvf ${keyTarFile} .ssh/*
    fi
    echo "KEY_GENERATED_SUCCESSFULLY"
fi