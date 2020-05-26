#!/bin/bash
########################################################################
#
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
# Description:
# Script to deploy cluster kubernetes cluster using aks-engine
#
########################################################################

AKS_ENGINE_DIR="aks-engine"
RESOURCE_GROUP=""
DNS_PREFIX=""

# Function to install AKS engine binary
function InstallAKSEngine() {
    local ret=1
    if [[ ! -z ${AKS_ENGINE_BINARY_URL} ]];then
        curl -o get-akse.sh ${AKS_ENGINE_BINARY_URL}
        bash get-akse.sh
        output=$(aks-engine version)
        ret=$?
        LogMsg "$output"
    fi
    return $ret
}

# Function to clone aks-engine repo
function CloneAKSEngineRepo() {
    local ret=0
    pushd ${HOME}
    [[ -d ${AKS_ENGINE_DIR} ]] && rm -rf ${AKS_ENGINE_DIR}
    # clone aks-engine repo
    git clone ${AKS_ENGINE_URL} -o ${AKS_ENGINE_DIR}
    ret=$?
    popd
    return $ret
}

# Function to install all dependencies for e2e tests
function InstallDependencies() {
    local ret=0

    InstallAzureCli; ret=$?
    [[ $ret -ne 0 ]] && return $ret

    InstallKubectl; ret=$?
    [[ $ret -ne 0 ]] && return $ret

    return 0
}

# Function to start e2e test of aks-engine
function CreateKubernetesCluster() {
    local ret=1
    local SOURCE_DIR="${1}"

    [[ -z ${SOURCE_DIR} ]] && return $ret

    CreateResourceGroup ${RESOURCE_GROUP} ${LOCATION}; ret=$?
    if [[ $ret -ne 0 ]];then
        LogErr "ERROR: CreateResourceGroup failed" "$ret"
        return $ret
    fi
    DNS_PREFIX="${RESOURCE_GROUP}"

    pushd ${SOURCE_DIR}
    aks-engine deploy --subscription-id ${SUBSCRIPTION_ID}\
            --dns-prefix ${DNS_PREFIX} \
            --resource-group ${RESOURCE_GROUP} \
            --location ${LOCATION} \
            --api-model ${API_MODEL} \
            --client-id ${CLIENT_ID} \
            --client-secret ${CLIENT_SECRET} \
            --set servicePrincipalProfile.clientId=${CLIENT_ID} \
            --set servicePrincipalProfile.secret=${CLIENT_SECRET}

    ret=$?
    popd
    return $ret
}

# Function to verify the deployed cluster
function VerifyClusterDeployment() {
    local ret=1
    local SOURCE_DIR="${1}"

    [[ -z ${SOURCE_DIR} ]] && return $ret
    export KUBECONFIG=${SOURCE_DIR}/_output/${RESOURCE_GROUP}/kubeconfig/kubeconfig.westus2.json

    output=$(kubectl cluster-info)
    LogMsg "${output}"

    local master_name=$(az vm list -g ${RESOURCE_GROUP} | jq '.[0].name')
    master_name=$(echo ${master_name} | sed s/\"//g)
    LogMsg "${master_name}"
    [[ ! -z ${master_name} ]] && ret=0

    return $ret
}

#######################################################################
#
# Main script body
#
#######################################################################

# Source containers_utils.sh
. containers_utils.sh || {
    echo "ERROR: unable to source containers_utils.sh"
    echo "TestAborted" > state.txt
    exit 0
}

UtilsInit
GetDistro

InstallMiscUtility; ret=$?
[[ $ret -eq 2 ]] && HandleSkip "INFO: InstallMiscUtility skipped" "$ret"
[[ $ret -ne 0 ]] && HandleAbort "ERROR: InstallMiscUtility failed" "$ret"

ConfigureEnvironment; ret=$?
[[ $ret -eq 2 ]] && HandleAbort "ERROR: ConfigureEnvironment failed" "$ret"

InstallDependencies; ret=$?
[[ $ret -eq 2 ]] && HandleSkip "INFO: InstallDependencies skipped" "$ret"
[[ $ret -ne 0 ]] && HandleFailure "ERROR: InstallDependencies failed" "$ret"

InstallAKSEngine; ret=$?
[[ $ret -ne 0 ]] && HandleFailure "ERROR: InstallAKSEngine failed" "$ret"

CloneAKSEngineRepo; ret=$?
[[ $ret -ne 0 ]] && HandleFailure "ERROR: CloneAKSEngineRepo failed" "$ret"
AKS_ENGINE_SRC_DIR="${HOME}/${AKS_ENGINE_DIR}"

LoginToAzure ${CLIENT_ID} ${CLIENT_SECRET} ${TENANT_ID}; ret=$?
[[ $ret -ne 0 ]] && HandleFailure "ERROR: LoginToAzure failed" "$ret"

GetResourceGroupName ${LOCATION}; ret=$?
[[ $ret -ne 0 ]] && HandleFailure "ERROR: GetResourceGroupName failed" "$ret"

RegisterResourceCleanup

while true;do
    count=$((count + 1))
    CreateKubernetesCluster ${AKS_ENGINE_SRC_DIR}; ret=$?
    [[ $ret -eq 0 ]] && break
    if [[ $count -ge 3 ]];then
        HandleFailure "ERROR: CreateKubernetesCluster failed" "$ret"
    else
        LogMsg "CreateKubernetesCluster: Failed: $ret, retrying $count"
    fi
done

VerifyClusterDeployment ${AKS_ENGINE_SRC_DIR}; ret=$?
[[ $ret -ne 0 ]] && HandleFailure "ERROR: VerifyClusterDeployment failed" "$ret"

SetTestStateCompleted
exit 0
