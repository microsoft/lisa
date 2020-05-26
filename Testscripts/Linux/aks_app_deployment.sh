#!/bin/bash
########################################################################
#
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
# Description:
# Script to test the application deployment to aks kubernetes cluster
#
########################################################################

RESOURCE_GROUP=""
APPLICATION_MANIFEST_FILE="azure-vote.yaml"
SERVICE_NAME="azure-vote-front"

# Function to install all dependencies for e2e tests
function InstallDependencies() {
    local ret=0

    InstallAzureCli; ret=$?
    [[ $ret -ne 0 ]] && return $ret

    InstallKubectl; ret=$?
    [[ $ret -ne 0 ]] && return $ret

    return 0
}

# Function to generate the manifest file for application deployment
function GenerateManifestFile() {
cat > ${APPLICATION_MANIFEST_FILE} <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: azure-vote-back
spec:
  replicas: 1
  selector:
    matchLabels:
      app: azure-vote-back
  template:
    metadata:
      labels:
        app: azure-vote-back
    spec:
      nodeSelector:
        "beta.kubernetes.io/os": linux
      containers:
      - name: azure-vote-back
        image: redis
        resources:
          requests:
            cpu: 100m
            memory: 128Mi
          limits:
            cpu: 250m
            memory: 256Mi
        ports:
        - containerPort: 6379
          name: redis
---
apiVersion: v1
kind: Service
metadata:
  name: azure-vote-back
spec:
  ports:
  - port: 6379
  selector:
    app: azure-vote-back
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: azure-vote-front
spec:
  replicas: 1
  selector:
    matchLabels:
      app: azure-vote-front
  template:
    metadata:
      labels:
        app: azure-vote-front
    spec:
      nodeSelector:
        "beta.kubernetes.io/os": linux
      containers:
      - name: azure-vote-front
        image: microsoft/azure-vote-front:v1
        resources:
          requests:
            cpu: 100m
            memory: 128Mi
          limits:
            cpu: 250m
            memory: 256Mi
        ports:
        - containerPort: 80
        env:
        - name: REDIS
          value: "azure-vote-back"
---
apiVersion: v1
kind: Service
metadata:
  name: azure-vote-front
spec:
  type: LoadBalancer
  ports:
  - port: 80
  selector:
    app: azure-vote-front
EOF
[[ -f ${APPLICATION_MANIFEST_FILE} ]] && return 0 || return 1
}

# Function to deploy kubernetes cluster
function DeployKubernetesCluster() {
    local ret=1
    local count=0

    CreateResourceGroup ${RESOURCE_GROUP} ${LOCATION}; ret=$?
    if [[ $ret -ne 0 ]];then
        LogErr "ERROR: CreateResourceGroup failed" "$ret"
        return $ret
    fi

    AKS_CLUSTER_NAME="${RESOURCE_GROUP}-cluster"
    LogMsg "AKS_CLUSTER_NAME: ${AKS_CLUSTER_NAME}"

    # Retry three time in case of failure
    while true; do
        az aks create --service-principal ${CLIENT_ID} \
                --client-secret ${CLIENT_SECRET} \
                --resource-group ${RESOURCE_GROUP} \
                --name ${AKS_CLUSTER_NAME} \
                --node-count 1 \
                --enable-addons monitoring \
                --generate-ssh-keys
        ret=$?
        LogMsg "az aks create returns: $ret count: $count"
        [[ $ret -eq 0 ]] && break
        [[ $count -ge 3 ]] && break
        count=$((count + 1))
    done

    if [[ $ret -eq 0 ]]; then
        # Download the kubernetes cluster credential for kubectl to connect to cluster
        az aks get-credentials --resource-group ${RESOURCE_GROUP} \
                --name ${AKS_CLUSTER_NAME}

        output=$(kubectl get nodes)
        echo ${output} | grep -qw "Ready"
        ret=$?
        LogMsg "DeployKubernetesCluster: Node status: ${output}"
    fi

    return $ret
}

# Function to deploy application in kubernetes cluster
function DeployApplication() {
    local ret=1
 
    GenerateManifestFile; ret=$?
    LogMsg "GenerateManifestFile returns: $ret"
    if [[ $ret -eq 0 ]];then
        # Deploy application using manifest file.
        kubectl apply -f ${APPLICATION_MANIFEST_FILE}; ret=$?
        LogMsg "kubectl apply: returns: $ret"
    fi

    return $ret
}

# Function to verify the deployed application
function VerifyApplicationDeployment() {
    local ret=1
    local count=0
    local output=""
    while true; do
        output=$(kubectl get service ${SERVICE_NAME} -o json)
        LogMsg "VerifyApplicationDeployment: kubestl Output: $output"
        ip_address=$(echo $output | jq '.status.loadBalancer.ingress[0].ip' | sed 's/\"//g')
        [[ $ip_address != null ]] && break
        [[ $count -ge 5 ]] && return $ret
        count=$((count + 1))
        sleep 5
    done

    LogMsg "curl -s http://${ip_address}"
    output=$(curl -s http://${ip_address})
    LogMsg "VerifyApplicationDeployment: Application Output: $output"
    echo $output  | grep -wq Cats; ret=$?
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

DeployKubernetesCluster; ret=$?
[[ $ret -ne 0 ]] && HandleFailure "ERROR: DeployKubernetesCluster failed" "$ret"

DeployApplication; ret=$?
[[ $ret -ne 0 ]] && HandleFailure "ERROR: DeployApplication failed" "$ret"

VerifyApplicationDeployment; ret=$?
[[ $ret -ne 0 ]] && HandleFailure "ERROR: VerifyApplicationDeployment failed" "$ret"

SetTestStateCompleted
exit 0