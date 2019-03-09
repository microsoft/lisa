#!/bin/bash

########################################################################
#
# Linux on Hyper-V and Azure Test Code, ver. 1.0.0
# Copyright (c) Microsoft Corporation
#
# All rights reserved.
# Licensed under the Apache License, Version 2.0 (the ""License"");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
#
# THIS CODE IS PROVIDED *AS IS* BASIS, WITHOUT WARRANTIES OR CONDITIONS
# OF ANY KIND, EITHER EXPRESS OR IMPLIED, INCLUDING WITHOUT LIMITATION
# ANY IMPLIED WARRANTIES OR CONDITIONS OF TITLE, FITNESS FOR A PARTICULAR
# PURPOSE, MERCHANTABLITY OR NON-INFRINGEMENT.
#
# See the Apache Version 2.0 License for specific language governing
# permissions and limitations under the License.
#
# How to use?
# .\Register-Redhat.sh -Username <RHN username> -Password <RHN Password>
########################################################################
while echo $1 | grep ^- > /dev/null; do
    eval $( echo $1 | sed 's/-//g' | tr -d '\012')=$2
    shift
    shift
done

Register_vm()
{
    subscription-manager register --force --username=${Username} --password=${Password}
    if [ $? -ne 0 ]; then
        echo "RHEL_REGISTRATION_FAILED"
    else
        echo "RHEL_REGISTERED"
    fi
    subscription-manager attach --auto
    subscription-manager repos --disable=rhel-7-server-rt-beta-rpms
}

#######################################################################
# Main script body
#######################################################################

# Check if distro is RHEL.If not, skip the registration.
DISTRO=$(grep -ihs "Ubuntu\|SUSE\|Fedora\|Debian\|CentOS\|Red Hat Enterprise Linux\|clear-linux-os\|CoreOS" /{etc,usr/lib}/{issue,*release,*version})
case $DISTRO in
    *Red*Hat*)
        Register_vm
        ;;
    *)
    echo RHEL_REGISTRATION_SKIPPED
esac
exit 0