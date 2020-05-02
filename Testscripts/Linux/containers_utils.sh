#!/bin/bash
########################################################################
#
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
# Description:
#   Utility function for managing containers.
#
########################################################################

DOCKER_BUILD_OUTPUT="docker_build.log"
DOCKER_RUN_OUTPUT="docker_run.log"

# Source the command utility functions
. utils.sh || {
    echo "ERROR: unable to source utils.sh!"
    exit 0
}

# Function to abort the test
#   Param1: Error message for logging
#   Param2: Error code for logging
HandleAbort() {
    local err_msg=$1
    local err_code=$2

    echo "TestAborted" > state.txt
    LogErr "$err_msg (ret: $err_code)"
    exit 0
}

# Function to handle the failure
#   Param1: Error message for logging
#   Param2: Error code for logging
HandleFailure() {
    local err_msg=$1
    local err_code=$2

    SetTestStateFailed
    LogErr "$err_msg (ret: $err_code)"
    exit 0
}

# Function to handle the failure
#   Param1: Error message for logging
#   Param2: Error code for logging
HandleSkip() {
    local err_msg=$1
    local err_code=$2

    SetTestStateSkipped
    LogErr "$err_msg (ret: $err_code)"
    exit 0
}

# Function to verify docker engine is started correctly
function VerifyDockerEngine() {
    LogMsg "VerifyDockerEngine on $DISTRO"

    output=$(docker run hello-world)
    if [ $? -ne 0 ]; then
        LogErr "Fail to run docker run hello-world"
        return 1
    fi
    LogMsg "VerifyDockerEngine: hello-world output - $output"
}

# Function to start docker engine
function StartDockerEngine() {
    LogMsg "Start docker engine"
    systemctl start docker || service docker start
    if [ $? -ne 0 ]; then
        LogErr "Fail to start docker service."
        return 1
    fi
}

# Function to install docker engine
function InstallDockerEngine() {
    local ret=2

    LogMsg "InstallDockerEngine on $DISTRO"
    update_repos

    case $DISTRO in
        ubuntu*|debian*)
            LogMsg "Uninstall old versions of Docker."
            apt-get remove -y docker docker-engine docker.io containerd runc
            LogMsg "Install packages apt-transport-https ca-certificates curl gnupg-agent software-properties-common."
            apt-get update
            install_package "apt-transport-https ca-certificates curl gnupg-agent software-properties-common"
            LogMsg "Add Docker's official GPG key."
            curl -fsSL https://download.docker.com/linux/$DISTRO_NAME/gpg | sudo apt-key add -
            LogMsg "Set up the stable repository."
            add-apt-repository "deb [arch=amd64] https://download.docker.com/linux/$DISTRO_NAME $(lsb_release -cs) stable"
            apt-get update
            install_package "docker-ce docker-ce-cli containerd.io"
            ret=$?
        ;;

        centos*|redhat*)
            LogMsg "Uninstall old versions of Docker."
            yum remove -y docker docker-client docker-client-latest docker-common docker-latest docker-latest-logrotate docker-logrotate docker-engine
            LogMsg "Install package yum-utils."
            install_package "yum-utils"
            LogMsg "Add repo https://download.docker.com/linux/centos/docker-ce.repo."
            yum-config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
            if [[ $DISTRO_VERSION == 8* ]];then
                yum install --nogpgcheck -y docker-ce docker-ce-cli containerd.io --nobest
            elif [[ $DISTRO_VERSION == 7* ]];then
                yum install http://mirror.centos.org/centos/7/extras/x86_64/Packages/container-selinux-2.107-1.el7_6.noarch.rpm
                yum install --nogpgcheck -y docker-ce docker-ce-cli containerd.io
            else
                HandleSkip "Test not supported for RH/CentOS $DISTRO_VERSION" $ret
            fi
            ret=$?
        ;;

    *)
        HandleSkip "$DISTRO not supported" $ret
    esac
    [[ $ret -ne 0 ]] && return $ret

    StartDockerEngine; ret=$?
    [[ $ret -ne 0 ]] && return $ret

    VerifyDockerEngine; ret=$?
    [[ $ret -ne 0 ]] && return $ret

    return $ret
}

# Function to remove docker container
function RemoveDockerContainer() {
    [[ -z "$1" ]] && {
        LogErr "RemoveDockerContainer: Docker container name / id missing."
        return 1
    } || local container_name="$1"

    docker rm $container_name
}

# Function to remove docker image
function RemoveDockerImage() {
    [[ -z "$1" ]] && {
        LogErr "RemoveDockerImage: Docker container image name / id missing."
        return 1
    } || local container_img_name="$1"

    docker rmi $container_img_name
}

# Function to build docker image
# Usage: BuildDockerImage <Param1> <Param2>
#    Param1: container image name (optional, Default: testimg)
#    Param2: Docker filename (optional, Default: Dockerfile)
function BuildDockerImage() {
    local container_img_name=testimg
    local docker_file=Dockerfile
    [[ ! -z "$1" ]] && local container_img_name=$1
    [[ ! -z "$2" ]] && local docker_file=$2

    docker build -t $container_img_name -f $docker_file . 1> ${DOCKER_BUILD_OUTPUT} 2>&1
    if [ $? -ne 0 ]; then
        LogErr "docker image build failed: $(cat ${DOCKER_BUILD_OUTPUT})"
        return 1
    fi
    LogMsg "DOCKER BUILD OUTPUT: "
    LogMsg "$(cat ${DOCKER_BUILD_OUTPUT})"
}

# Function to run the docker container
# Usage: RunDockerContainer <Param1> <Param2>
#    Param1: container image name
#    Param2: container name (optional, Default: testcon)
function RunDockerContainer() {
    [[ -z "$1" ]] && {
        LogErr "RunDockerContainer: Docker container image name / id missing."
        return 1
    } || local container_img_name="$1"

    local container_name=testcon
    [[ ! -z "$2" ]] && container_name=$2

    docker run --name $container_name $container_img_name 1> ${DOCKER_RUN_OUTPUT} 2>&1
    if [ $? -ne 0 ]; then
        LogErr "docker run failed: ${DOCKER_RUN_OUTPUT}."
        return 1
    fi
    LogMsg "DOCKER RUN OUTPUT: "
    LogMsg "$(cat ${DOCKER_RUN_OUTPUT})"
}

# Function to install docker compose
function InstallDockerCompose() {
    LogMsg "Download the current stable release of Docker Compose"
    curl -L "https://github.com/docker/compose/releases/download/1.25.4/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
    chmod +x /usr/local/bin/docker-compose
    ln -s /usr/local/bin/docker-compose /usr/bin/docker-compose
    docker-compose --version
    if [ $? -ne 0 ]; then
        LogErr "Fail to install docker-compose."
        return 1
    fi
    return 0
}
