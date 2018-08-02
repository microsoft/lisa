#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
# Description : Enables root user and sets password. Needs to run with sudo permissions.
# How to use : ./enableRoot.sh -password <new_root_password>

while echo $1 | grep ^- > /dev/null; do
    eval $( echo $1 | sed 's/-//g' | tr -d '\012')=$2
    shift
    shift
done

password=$password
sshd_configFilePath="/etc/ssh/sshd_config"
sshdServiceName="sshd"
usermod --password $(echo $password | openssl passwd -1 -stdin) root
if [ $? == 0 ]; then
    sed -i 's/.*PermitRootLogin.*/PermitRootLogin yes/g' $sshd_configFilePath
    if [ $? == 0 ]; then
        echo "$sshd_configFilePath verifed for root login."
        echo "ROOT_PASSWRD_SET"
        service $sshdServiceName restart || systemctl restart sshd.service
        sshdServiceStatus=$?
        if [ $sshdServiceStatus != 0 ]; then
                service ssh restart
                sshdServiceStatus=$?
        fi
    else
        echo "$sshd_configFilePath verification failed for root login."
        echo "ROOT_PASSWORD_SET_SSHD_CONFIG_FAIL"
    fi
else
    echo "Unable to set root password."
    echo "ROOT_PASSWORD_NOT_SET"
fi
if [ $sshdServiceStatus == 0 ]; then
    echo "SSHD_RESTART_SUCCESSFUL"
else
    echo "SSHD_RESTART_FAIL"
fi
exit 0
