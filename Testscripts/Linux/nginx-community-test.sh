#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
###############################################################################
#
# Description:
#
###############################################################################

# Function to install the dependant packages
function InstallDependantPackages() {
    local ret=0
    case $DISTRO in
      "ubuntu"*)
        LogMsg "Installing dependencies..."
        common_packages=(m4 bison flex make gcc psmisc autoconf automake)
        install_package "${common_packages[@]}"
        deb_packages=(git libaio-dev libattr1 libcap-dev keyutils \
                       libdb4.8 libberkeleydb-perl expect dh-autoreconf gdb \
                       libnuma-dev quota genisoimage db-util unzip exfat-utils)
        install_package "${deb_packages[@]}"
        ret=$?
        ;;
      "mariner")
        tdnf install -y build-essential pcre-devel.x86_64 httpd fcgi \
                        fcgi-devel perl-IO-Socket-SSL.noarch libxslt \
                        libxslt-devel zlib-devel git make
        ret=$?
        ;;
      *)
        LogMsg "Unknown distro $DISTRO, continuing to try for RPM installation"
        ret=2
        ;;
    esac
    return $ret
}

# Function to build nginx package
function BuildNginx() {
    local ret = 0
    local NGINX_FOLDER="nginx"
    LogMsg "Building nginx..."
    [[ -z ${NGINX_REPO} ]] && {
        LogErr "BuildNginx::nginx repo not available"
        return 1
    }

    [ -d ${NGINX_FOLDER} ] && rm -rf ${NGINX_FOLDER}
    git clone --branch master ${NGINX_REPO} -o ${NGINX_FOLDER}
    pushd ${NGINX_FOLDER}
    ./auto/configure \
        --with-http_ssl_module \
        --with-http_slice_module \
        --with-pcre-jit \
        --with-threads  \
        --with-http_auth_request_module \
        --with-http_realip_module \
        --with-debug \
        --with-stream \
        --with-stream_ssl_module \
        --with-stream_realip_module \
        --with-stream_ssl_preread_module \
        --with-http_perl_module \
        --with-mail \
        --with-mail_ssl_module \
        --with-http_sub_module \
        --with-http_xslt_module \
        --with-http_dav_module \
        --with-http_addition_module \
        --with-mail_ssl_module \
        --with-http_stub_status_module \
        --with-http_v2_module

    make -j$(nproc); ret=$?
    popd
    [[ $ret -ne 0 ]] && ret=1

    return $ret
}

# Function to clone nginx_tests repo and execute tests
function RunNginxTest() {
    local ret=0
    local NGINX_TEST_FOLDER="nginx-tests"
    [[ -z ${NGINX_TEST_REPO} ]] && {
        LogErr "BuildNginx::nginx repo not available"
        return 1
    }
    
    [ -d ${NGINX_TEST_FOLDER} ] && rm -rf ${NGINX_TEST_FOLDER}
    
    LogMsg "Running nginx_tests ..."
    git clone --branch master ${NGINX_TEST_REPO} -o ${NGINX_TEST_FOLDER}

    #run the test
    pushd ${NGINX_TEST_FOLDER}
    sudo -u lisa prove . | tee nginx-test.log

    ret=$?
    nginxTestResult=$(tail -1  $execute_path/nginx-test.log | grep "PASS" | wc -l)
    logs=$(cat nginx-test.log)
    popd

    LogMsg "$logs"

    [[ $nginxTestResult -ne 0 ]] && ret=1
    return $ret
}

# Function to check the execution status
function CheckExecStatus() {
    func_name=$1
    status=$2
    if [[ ${status} -eq 0 ]];then
        LogMsg "${func_name} returned success (${status})"
    elif [[ ${status} -eq 2 ]];then
        LogMsg "Skipping test - ${func_name} returned $status"
        SetTestStateSkipped
        exit 0
    else
        LogErr "${func_name} failed ($status)"
        SetTestStateFailed
        exit 0
    fi
}

#######################################################################
#
# Main script body
#
#######################################################################

# Source utils.sh
. utils.sh || {
    echo "Error: unable to source utils.sh!"
    echo "TestAborted" > state.txt
    exit 0
}

. constants.sh || {
    LogMsg "No constants.sh found"
}

# Source constants file and initialize most common variables
UtilsInit

# Checks what Linux distro we are running on
GetDistro
update_repos

InstallDependantPackages; ret=$?
CheckExecStatus "InstallDependantPackages" $ret

BuildNginx; ret=$?
CheckExecStatus "BuildNginx" $ret

RunNginxTest; ret=$?
CheckExecStatus "RunNginxTest" $ret

SetTestStateCompleted
exit 0