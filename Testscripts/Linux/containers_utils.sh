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

export GOPATH=${HOME}/go
export GOBIN=${GOPATH}/bin
export PATH=${PATH}:/usr/local/go/bin:${GOPATH}/bin

# Status for each test script to use
FAIL_ID=1
SKIP_ID=2

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

# Wrapper function to handle the different return status from test scripts
function HandleTestResults() {
    local test_status=${1}
    local msg="${2}"
    [[ $test_status -eq 0 ]] && return 0
    [[ $test_status -eq ${SKIP_ID} ]] && HandleSkip "INFO: ${msg} skipped" "$test_status"
    [[ $test_status -eq ${FAIL_ID} ]] && HandleFailure "ERR: ${msg} failed" "$test_status"
    [[ $test_status -ne 0 ]] && HandleAbort "ERR: ${msg} failed unknown error" "$test_status"
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

# Function to set enviroment for Kubernetes cluster deployment
function ConfigureEnvironment() {
    local ret=0
    if [[ -f setenv ]];then
        dos2unix setenv
        . setenv || $ret=2
    fi
    return $ret
}

# Function to install go package
function InstallGo() {
    local ret=2
    GetOSVersion

    case $DISTRO in
        ubuntu*|debian*)
            LogMsg "InstallGo on $DISTRO"
            update_repos
            apt install -y build-essential gcc
            if [[ ! -z ${GO_LANG_DOWNLOAD_URL} ]];then
                wget ${GO_LANG_DOWNLOAD_URL} -O go.linux-amd64.tar.gz
                tar -C /usr/local -zxf go.linux-amd64.tar.gz
                [[ $? -ne 0 ]] && ret=1 || ret=0
            else
                ret=1
            fi
            if [[ $ret -eq 0 ]];then
                mkdir -p ${GOPATH}; mkdir -p ${GOBIN}
            fi
        ;;

        *)
           HandleSkip "$DISTRO not supported" $ret
    esac
    LogMsg "InstallGo: return: $ret"
    return $ret
}

# Function to install kubectl for query aks cluster
function InstallKubectl() {
    local ret=2
    GetOSVersion

    case $DISTRO in
        ubuntu*|debian*)
            LogMsg "InstallKubectl on $DISTRO"
            apt-get install -y ca-certificates curl apt-transport-https lsb-release gnupg
            curl -s https://packages.cloud.google.com/apt/doc/apt-key.gpg | sudo apt-key add -
            echo "deb https://apt.kubernetes.io/ kubernetes-xenial main" | sudo tee -a /etc/apt/sources.list.d/kubernetes.list
            update_repos
            apt-get install -y kubectl
            ln -sf /usr/bin/kubectl /usr/bin/k
            [[ $? -ne 0 ]] && ret=1 || ret=0
        ;;

        *)
           HandleSkip "$DISTRO not supported" $ret
    esac
    LogMsg "InstallKubectl: return: $ret"
    return $ret
}

# Function to install AzCopy to copy the artifacts from Azure
# storage account
function InstallAzCopy() {
    AZCOPY_FOLDERNAME="azcopy_linux"
    AZCOPY_TARBALL="${AZCOPY_FOLDERNAME}.tar.gz"

    [[ -z ${AZCOPY_DOWNLOAD_URL} ]] && {
        LogErr "AZCOPY DOWNLOAD URL MISSING"
        return 1
    }
    wget ${AZCOPY_DOWNLOAD_URL} -O ${AZCOPY_TARBALL}
    [[ ! -f ${AZCOPY_TARBALL} ]] && return 1

    [[ -d ${AZCOPY_FOLDERNAME} ]] && rm -rf ${AZCOPY_FOLDERNAME}
    mkdir ${AZCOPY_FOLDERNAME}
    tar -xf ${AZCOPY_TARBALL} --strip-component 1 -C ${AZCOPY_FOLDERNAME}

    AZCOPY_PATH="$(pwd)/${AZCOPY_FOLDERNAME}"
    export PATH=$PATH:${AZCOPY_PATH}

    rm -f ${AZCOPY_TARBALL}
    return 0
}

# Function to install Azure command line package
function InstallAzureCli() {
    local ret=2
    GetOSVersion

    case $DISTRO in
        ubuntu*|debian*)
            LogMsg "InstallAzureCli on $DISTRO"
            update_repos
            apt-get install -y ca-certificates curl apt-transport-https lsb-release gnupg
            curl -sL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor | tee /etc/apt/trusted.gpg.d/microsoft.asc.gpg > /dev/null
            AZ_REPO=$(lsb_release -cs)
            echo "deb [arch=amd64] https://packages.microsoft.com/repos/azure-cli/ $AZ_REPO main" | tee /etc/apt/sources.list.d/azure-cli.list
            apt-get update
            apt-get install -y azure-cli
            [[ $? -ne 0 ]] && ret=1 || ret=0
        ;;

        *)
           HandleSkip "$DISTRO not supported" $ret
    esac
    LogMsg "InstallAzureCli: return: $ret"
    return $ret
}

# Function to install the JSON utility for Azure query processing
function InstallMiscUtility() {
    local ret=2
    GetOSVersion

    case $DISTRO in
        ubuntu*|debian*)
            LogMsg "InstallMiscUtility on $DISTRO"
            update_repos
            apt-get install -y jq dos2unix
            [[ $? -ne 0 ]] && ret=1 || ret=0
        ;;

        *)
           HandleSkip "$DISTRO not supported" $ret
    esac
    LogMsg "InstallMiscUtility: return: $ret"
    return $ret
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
    GetOSVersion
    pack_list=(docker-ce-cli containerd.io docker-ce)
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
            release=$(lsb_release -cs)
            add-apt-repository -y "deb https://download.docker.com/linux/$DISTRO_NAME ${release} stable"
            if [[ $os_RELEASE = '14.04' ]]; then
                pack_list=(docker-ce)
            fi
            apt-get update
            for package in "${pack_list[@]}"; do
                check_package "$package"
                if [ $? -eq 0 ]; then
                    install_package "$package"
                fi
            done
            ret=$?
        ;;

        centos*|redhat*|almalinux*)
            LogMsg "Uninstall old versions of Docker."
            yum remove -y docker docker-client docker-client-latest docker-common docker-latest docker-latest-logrotate docker-logrotate docker-engine
            LogMsg "Install package yum-utils."
            install_package "yum-utils"
            LogMsg "Add repo https://download.docker.com/linux/centos/docker-ce.repo."
            yum-config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
            if [[ $DISTRO_VERSION == 8* ]];then
                sed -i -e 's/$releasever/8/g' /etc/yum.repos.d/docker-ce.repo
                yum install --nogpgcheck -y docker-ce docker-ce-cli containerd.io --nobest --allowerasing
            elif [[ $DISTRO_VERSION == 7* ]];then
                yum install -y http://mirror.centos.org/centos/7/extras/x86_64/Packages/container-selinux-2.107-1.el7_6.noarch.rpm
                for package in "${pack_list[@]}"; do
                    check_package "$package"
                    if [ $? -eq 0 ]; then
                        install_package "$package"
                    fi
                done
            else
                HandleSkip "Test not supported for RH/CentOS $DISTRO_VERSION" $ret
            fi
            ret=$?
        ;;

        mariner*)
            LogMsg "Docker is installed by default in $DISTRO"
            ret=0
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
#    Param3: volume
function RunDockerContainerAttachingVolume() {
    [[ -z "$1" ]] && {
        LogErr "RunDockerContainer: Docker container image name / id missing."
        return 1
    } || local container_img_name="$1"

    local container_name=testcon
    [[ ! -z "$2" ]] && container_name=$2

    [[ -z "$3" ]] && {
        LogErr "RunDockerContainer: Docker container volume missing."
        return 1
    } || local container_volume="$3"

    docker run -v ${container_volume} --name $container_name $container_img_name 1> ${DOCKER_RUN_OUTPUT} 2>&1
    if [ $? -ne 0 ]; then
        LogErr "docker run failed: ${DOCKER_RUN_OUTPUT}."
        return 1
    fi
    LogMsg "DOCKER RUN OUTPUT: "
    LogMsg "$(cat ${DOCKER_RUN_OUTPUT})"
}

# Function to import the docker image from tarball
function ImportDockerImage() {
    DOCKER_IMPORT_OUTPUT="docker_import.log"
    [[ -z "$1" ]] && {
        LogErr "ImportDockerImage: container image tarball missing."
        return 1
    } || local container_img="$1"

    local container_name="testcon"
    [[ ! -z "$2" ]] && container_name=$2

    docker import ${container_img} ${container_name} 1> ${DOCKER_IMPORT_OUTPUT} 2>&1
    LogMsg "ImportDockerImage OUTPUT: ${DOCKER_IMPORT_OUTPUT}"
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

# Function to login to azure using service principle
function LoginToAzure() {
    local CLIENT_ID=${1}
    local CLIENT_SECRET=${2}
    local TENANT_ID=${3}
    az login --service-principal --username ${CLIENT_ID} --password ${CLIENT_SECRET} --tenant ${TENANT_ID}
    [[ $? -ne 0 ]] && return 1
    az account set --subscription ${SUBSCRIPTION_ID}
    return 0
}

# Function to generate RG name for the Kubernetes cluster deployment
function GetResourceGroupName() {
    local status=true
    local RG_NAME=""
    local LOCATION="${1}"

    while true;do
        RG_NAME="LISAv2-k8s-${LOCATION}-${RANDOM}"
        status=$(az group exists -n ${RG_NAME})
        [[ $status == false ]] && break
    done
    LogMsg "GetResourceGroupName:: RESOURCE_GROUP=${RG_NAME}"
    export RESOURCE_GROUP="${RG_NAME}"
}

# Function to create the resource group
function CreateResourceGroup() {
    local ret=1
    local RESOURCE_GROUP=${1}

    [[ -z ${RESOURCE_GROUP} ]] && return $ret

    local status=$(az group exists -n ${RESOURCE_GROUP})
    LogMsg "az group exists -n ${RESOURCE_GROUP} returned: $status"
    if [[ $status == false ]];then
        LogMsg "az group create --name ${RESOURCE_GROUP} --location ${LOCATION}"
        az group create --name ${RESOURCE_GROUP} --location ${LOCATION}
        ret=$?
    fi
    return $ret
}

# Function to clean up the resources
function CleanupResources() {
    [[ -z ${RESOURCE_GROUP} ]] && return 0

    local status=$(az group exists -n ${RESOURCE_GROUP})
    LogMsg "CleanupResources:: az group exists -n ${RESOURCE_GROUP} return: $status"
    if [[ $status == true ]];then
        LogMsg "CleanupResources:: az group delete --name ${RESOURCE_GROUP} --no-wait -y"
        az group delete --name ${RESOURCE_GROUP} --no-wait -y
    fi
    return 0
}

# Function to register resource clean up when the script exits
function RegisterResourceCleanup() {
    trap "CleanupResources" EXIT
}

# Function to download file from Azure storage account
function DownloadFileFromAzStorage() {
    AZCOPY_DOWNLOAD_LOG="azcopy_download.log"
    [[ -z "$1" ]] && {
        LogErr "DownloadFileFromAzStorage: Download URL missing"
        return 1
    } || local download_url="$1"

    [[ -z "$2" ]] && {
        LogErr "DownloadFileFromAzStorage: SAS TOKEN missing."
        return 1
    } || local sas_token="$2"

    [[ -z "$3" ]] && {
        LogErr "DownloadFileFromAzStorage: Destination filename missing."
        return 1
    } || local dest_filename="$3"

    azcopy copy ${download_url}${sas_token} ${dest_filename} 1> ${AZCOPY_DOWNLOAD_LOG} 2>&1
    LogMsg "$(cat ${AZCOPY_DOWNLOAD_LOG})"
    rm -f ${AZCOPY_DOWNLOAD_LOG}

    [[ ! -f ${dest_filename} ]] && return 1
    return 0
}
