#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
# THIS SCRIPT DETECT FOLLOWING DISTROS:
#  UBUNTU [VERSION INDEPENDANT]
#  CENTOS [VERSION INDEPENDANT]
#  SUSE LINUX ENTERPRISE SERVER [VERSION INDEPENDANT]
#  OPENSUSE [VERSION INDEPENDANT]
#  REDHAT
#  ORACLELINUX
#  FEDORA
DetectDistro()
{
while echo "$1" | grep ^- > /dev/null; do
    eval $( echo "$1" | sed 's/-//g' | tr -d '\012')="$2"
    shift
    shift
done
        if [ -e /etc/debian_version ]; then
		        tmp=$(cat /etc/*-release)
                if [[ "$tmp" == *Ubuntu* ]]; then
                    echo "UBUNTU"
                    exitVal=0
                else
                    echo "DEBIAN"
                    exitVal=0
                fi
        elif [ -e /etc/redhat-release ]; then
                tmp=$(cat /etc/redhat-release)
                if [ -e /etc/oracle-release ]; then
                    tmp=$(cat /etc/oracle-release)
                    if [[ "$tmp" == *Oracle* ]]; then
                        echo "ORACLELINUX"
                        exitVal=0
                    else
                        echo "Unknown"
                        exitVal=1
                    fi
                elif [[ "$tmp" == *CentOS* ]]; then
                    echo "CENTOS"
                    exitVal=0
                elif [[ "$tmp" == *Fedora* ]]; then
                    echo "FEDORA"
                    exitVal=0
                elif [[ "$tmp" == *Red* ]]; then
                    echo "REDHAT"
                    exitVal=0
                else
                    echo "Unknown"
                    exitVal=1
                fi
        elif [ -e /etc/SuSE-release ]; then
                tmp=$(cat /etc/SuSE-release)
                if [[ "$tmp" == *Enterprise* ]]; then
                    echo "SLES"
                    exitVal=0
                elif [[ "$tmp" == *open* ]]; then
                    echo "SUSE"
                    exitVal=0
                else
                    echo "Unknown"
                fi
        elif [ -e /etc/os-release ]; then
                tmp=$(cat /etc/os-release)
                if [[ "$tmp" == *coreos* ]]; then
                    echo "COREOS"
                    exitVal=0
                elif [[ "$tmp" =~ "SUSE Linux Enterprise Server 15" ]]; then
                    echo "SLES 15"
                    exitVal=0
                else
                    echo "Unknown"
                fi
        elif [ -e /usr/share/clear/version ]; then
                tmp=$(cat /usr/share/clear/version)
                echo "CLEARLINUX"
                exitVal=0
        fi
return $exitVal
}
DetectDistro