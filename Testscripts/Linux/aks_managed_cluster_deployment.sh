#!/bin/bash
########################################################################
#
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
# Description:
# Script to deploy managed kubernetes cluster using aks
#
########################################################################

RESOURCE_GROUP=""

# Function to install all dependencies for e2e tests
function InstallDependencies() {
    local ret=0

    InstallAzureCli; ret=$?
    [[ $ret -ne 0 ]] && return $ret

    InstallKubectl; ret=$?
    [[ $ret -ne 0 ]] && return $ret

    return 0
}

# Function to deploy managed cluster using AKS
function DeployManagedKubernetesCluster() {
    local ret=1

    CreateResourceGroup ${RESOURCE_GROUP} ${LOCATION}; ret=$?
    if [[ $ret -ne 0 ]];then
        LogErr "ERROR: CreateResourceGroup failed" "$ret"
        return $ret
    fi
    AKS_CLUSTER_NAME="${RESOURCE_GROUP}-cluster"

    az aks create --service-principal ${CLIENT_ID} \
            --client-secret ${CLIENT_SECRET} \
            --resource-group ${RESOURCE_GROUP} \
            --name ${AKS_CLUSTER_NAME} \
            --node-count 1 \
            --enable-addons monitoring \
            --generate-ssh-keys
    ret=$?

    return $ret
}

# Function to verify the deployed cluster
function VerifyClusterDeployment()
{
    local ret=1
    # Download the kubernetes cluster credential for kubectl to connect to cluster
    az aks get-credentials --resource-group ${RESOURCE_GROUP} \
            --name ${AKS_CLUSTER_NAME}

    output=$(kubectl get nodes)
    echo ${output} | grep -qw "Ready"
    ret=$?
    LogMsg "${output}"
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

LoginToAzure ${CLIENT_ID} ${CLIENT_SECRET} ${TENANT_ID}; ret=$?
[[ $ret -ne 0 ]] && HandleFailure "ERROR: LoginToAzure failed" "$ret"

GetResourceGroupName ${LOCATION}; ret=$?
[[ $ret -ne 0 ]] && HandleFailure "ERROR: GetResourceGroupName failed" "$ret"

RegisterResourceCleanup

DeployManagedKubernetesCluster; ret=$?
[[ $ret -ne 0 ]] && HandleFailure "ERROR: DeployManagedKubernetesCluster failed" "$ret"

VerifyClusterDeployment; ret=$?
[[ $ret -ne 0 ]] && HandleFailure "ERROR: VerifyClusterDeployment failed" "$ret"

SetTestStateCompleted
exit 0