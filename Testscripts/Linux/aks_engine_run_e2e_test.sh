#!/bin/bash
########################################################################
#
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
# Description:
# Script to run the aks e2e test
#
########################################################################

BUILD_LOG=".aks_build.log"
TESTCASE_LIST=".aks_testcase_list"
TEST_RESULT="result_$(date +%d%m%y_%H%M%S).csv"
SSH_CLEANUP_RULE_DISABLE="enable_ssh_script"

AKS_ENGINE_DIR="aks-engine"

# E2E testcase exception list
e2e_test_exception_list=(
    "should have node labels and annotations added by E2E test runner"
)

# Function to clone aks-engine repo
function CloneAKSEngineRepo() {
    local ret=0

    mkdir -p ${GOPATH}/src/github.com/Azure/
    pushd ${GOPATH}/src/github.com/Azure/
    # clone aks-engine repo
    git clone ${AKS_ENGINE_URL} -o ${AKS_ENGINE_DIR}
    pushd ${AKS_ENGINE_DIR}
    make bootstrap && make
    ret=$?
    [[ $ret -eq 0 ]] && cp ./hack/tools/bin/* ${GOBIN}/
    popd; popd

    return $ret
}

# Function to install all dependencies for e2e tests
function InstallE2ETestDependencies() {
    local ret=0

    InstallAzureCli; ret=$?
    [[ $ret -ne 0 ]] && return $ret

    InstallKubectl; ret=$?
    [[ $ret -ne 0 ]] && return $ret

    InstallGo; ret=$?
    [[ $ret -ne 0 ]] && return $ret

    return $ret
}

# Function to generate SSK keys
function GenerateSSHKey() {
    ssh-keygen
    ssh-add ~/.ssh/id_rsa

    return 0
}

# Check whether test is added to exception list
function is_test_exempted() {
    local test_case=${1}
    for exception in "${e2e_test_exception_list[@]}";do
        [[ "${test_case}" == "${exception}" ]] && return 1
    done
    return 0
}

# Function to log all tests status
# e2e test has around 50 testcases and below logging will add logs for each test.
function PrintResult() {
    LogMsg "$(printf '%-80s %-20s %-20s %-20s \n' "$1" "---------" "$2" "$3")"
    printf '%s,%s,%s \n' "$1" "$2" "$3" >> ${TEST_RESULT}

    return 0
}

# Function to analyze the test logs to check the failures
function AnalyseTestResult() {
    [[ ! -f ${BUILD_LOG} ]] && return 1
    grep -wq "Fail" ${BUILD_LOG} && return 1
    grep -wq "SKIPPING" ${BUILD_LOG} && return 2

    return 0
}

# Function to generate a test case list from test script.
# Each test is executed as an individual test to capture the failure and easy identification
function GenerateTestCaseList() {
    local AKS_ENGINE_SRC="${1}"

    test_script="${AKS_ENGINE_SRC}/test/e2e/kubernetes/kubernetes_test.go"
    [[ ! -f ${test_script} ]] && return 1

    grep -r "It(" ${test_script} | \
    awk -F, '{print $1}'| sed -e 's/^[ \t\/\*It\("]*//' | sed -e 's/"//' > ${TESTCASE_LIST}

    return 0
}

# Function to flush the ssh clean up rule to allow kubernetes test case to run properly
function EnableSSH() {
    local RGROUP="$1"

    local NSG_NAME=$(az resource list --subscription ${SUBSCRIPTION_ID} -g ${RGROUP} --resource-type Microsoft.Network/networkSecurityGroups | jq '.[0].name')
    NSG_NAME=$(echo ${NSG_NAME} | sed s/\"//g)
# Generate a script for disabling the clean up rule for SSH
cat > ${HOME}/${SSH_CLEANUP_RULE_DISABLE} << EOF
#! /bin/bash
while true; do
az network nsg rule update --subscription "${SUBSCRIPTION_ID}" -g "${RGROUP}" --nsg-name "${NSG_NAME}" \
--name Cleanuptool-Allow-100 --source-address-prefixes "*" --protocol "*" 1> /dev/null 2>&1
sleep 5
done
EOF
    # Run the script in backgraound
    bash ${HOME}/${SSH_CLEANUP_RULE_DISABLE}&
    return 0
}

# Function to enable the ssh clean up rules
function DisableSSH() {
    pid=$(ps ax | grep ${SSH_CLEANUP_RULE_DISABLE} | grep -v grep | awk '{print $1}')
    [[ ! -z ${pid} ]] && kill -9 ${pid}
    return 0
}

# Function to start e2e test of aks-engine
function RunE2ETest() {
    local AKS_ENGINE_SRC="${1}"
    local build_status="Fail"
    local ret=0

    # Enable the test execution
    export SKIP_TEST=false

    [[ -z ${RESOURCE_GROUP} ]] && \
            return 1 || export NAME=${RESOURCE_GROUP}

    [[ -z "${AKS_ENGINE_SRC}" ]] && return 1
    [[ -z $AUTH_SOCK ]] && eval $(ssh-agent) || LogMsg "AUTH_SOCK: $AUTH_SOCK"

    # Enable SSH & wait for 60 seconds for ssh rules to be cleaned up
    EnableSSH ${RESOURCE_GROUP} && sleep 60

    # Run individual test for capturing more detailed logs for failure in e2e test
    while IFS= read -r testcase;do
        [[ -f ${BUILD_LOG} ]] && rm -f ${BUILD_LOG}
        # Skip the test which are exempted
        is_test_exempted "${testcase}"; ret=$?
        if [[ $ret -eq 1 ]];then
            LogMsg "RunE2ETest: ${testcase} EXEMPTED from test run"
            continue
        fi

        export GINKGO_FOCUS="$testcase"
        make -C ${AKS_ENGINE_SRC} test-kubernetes 1> ${BUILD_LOG} 2>&1
        [[ $? -eq 0 ]] && build_status="Pass"
        AnalyseTestResult; test_result=$?

        [[ $ret -eq 0 ]] && ret=$test_result
        [[ $test_result -eq 2 ]] && result="Skip"
        [[ $test_result -eq 1 ]] && result="Fail"
        [[ $test_result -eq 0 ]] && result="Pass"

        [[ $test_result -eq 1 ]] && LogErr "$(cat ${BUILD_LOG})"
        PrintResult "$testcase" "$build_status" "$result"
    done < ${TESTCASE_LIST}

    # Disable the ssh
    DisableSSH

    return $ret
}

# Function to deploy cluster using aks-engine
function DeployCluster() {
    local ret=1
    local AKS_ENGINE_SRC="${1}"

    [[ ! -z ${NAME} ]] && { \
        RESOURCE_GROUP=${NAME}
        LogMsg "SKIPPING CLUSTER DEPLOYMENT : ${RESOURCE_GROUP}"
        return 0
    }

    [[ -z "${AKS_ENGINE_SRC}" ]] && return $ret
    [[ -z $AUTH_SOCK ]] && eval $(ssh-agent) || LogMsg "AUTH_SOCK: $AUTH_SOCK"

    LogMsg "DEPLOYING CLUSTER"
    export SKIP_TEST=true
    make -C ${AKS_ENGINE_SRC} test-kubernetes 1> ${BUILD_LOG} 2>&1; ret=$?
    export RESOURCE_GROUP=$(cat ${BUILD_LOG} | grep "timeout 60 az group show -n" | awk '{print $8}' | head -1)
    LogMsg "RESOURCE_GROUP: $RESOURCE_GROUP"

    [[ ${ret} -ne 0 ]] && LogErr "$(cat ${BUILD_LOG})"

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

[[ -f ${TEST_RESULT} ]] && rm -f ${TEST_RESULT}

InstallMiscUtility; ret=$?
[[ $ret -eq 2 ]] && HandleSkip "INFO: InstallMiscUtility skipped" "$ret"
[[ $ret -ne 0 ]] && HandleAbort "ERROR: InstallMiscUtility failed" "$ret"

ConfigureEnvironment; ret=$?
[[ $ret -eq 2 ]] && HandleAbort "ERROR: ConfigureEnvironment failed" "$ret"

InstallE2ETestDependencies; ret=$?
[[ $ret -eq 2 ]] && HandleSkip "INFO: InstallE2ETestDependencies skipped" "$ret"
[[ $ret -ne 0 ]] && HandleFailure "ERROR: InstallE2ETestDependencies failed" "$ret"

CloneAKSEngineRepo; ret=$?
[[ $ret -ne 0 ]] && HandleFailure "ERROR: CloneAKSEngineRepo failed" "$ret"

AKS_ENGINE_SOURCE="${GOPATH}/src/github.com/Azure/aks-engine"
GenerateTestCaseList ${AKS_ENGINE_SOURCE}; ret=$?
[[ $ret -ne 0 ]] && HandleFailure "ERROR: GenerateTestCaseList failed" "$ret"

RegisterResourceCleanup

DeployCluster ${AKS_ENGINE_SOURCE}; ret=$?
[[ $ret -ne 0 ]] && HandleFailure "ERROR: DeployCluster failed" "$ret"

RunE2ETest ${AKS_ENGINE_SOURCE}; ret=$?
[[ $ret -ne 0 ]] && HandleFailure "ERROR: RunE2ETest failed" "$ret"

SetTestStateCompleted
exit 0