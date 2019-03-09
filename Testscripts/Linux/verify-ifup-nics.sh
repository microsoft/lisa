#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

# Source utils.sh
. utils.sh || {
    echo "ERROR: unable to source utils.sh!"
    echo "TestAborted" > state.txt
    exit 2
}

# Source constants file and initialize most common variables
UtilsInit

function main() {

    # Source constants file
    if [[ -f "constants.sh" ]]; then
        LogMsg "Sourcing constants.sh"
        # shellcheck disable=SC1091
        source "constants.sh"
    fi

    test_result=0

    if [[ "$TestIterations" == "" ]] || [[ -z $TestIterations ]]; then
        TestIterations=1
        LogMsg "Setting Test Iterations to $TestIterations"
    else
        LogMsg "Setting Test Iterations to $TestIterations from constants.sh"
    fi

    if [[ "$network_interface_count" == "" ]] || [[ -z $network_interface_count ]]; then
        network_interface_count=1
        LogMsg "Setting network_interface_count to ${network_interface_count}"
    else
        LogMsg "Setting network_interface_count to ${network_interface_count} from constants.sh"
    fi

    LogMsg "*********INFO: Starting test execution ... *********"
    UpdateSummary "Verifying ${network_interface_count} nics ${TestIterations} times."
    network_interface_prefix="eth"

    test_iteration=0
    while [[ $test_iteration -lt $TestIterations ]];
    do
        test_iteration=$(( test_iteration + 1 ))
        LogMsg "Test Iteration : $test_iteration"

        for eth_number in $(seq 0 $(( network_interface_count - 1 ))); do
            eth_name="${network_interface_prefix}${eth_number}"
            LogMsg "Checking if ${eth_name} is up and has a valid IP"
            eth_ip=$(ip a | grep "${eth_name}" | sed -n '2 p' | awk '{print $2}')
            if [[ "${eth_ip}" != '' ]];then
                UpdateSummary "[INFO]: IP for ${eth_name} is ${eth_ip}"
            else
                UpdateSummary "[ERROR]: IP for ${eth_name} is not set"
                eth_info=$(ip a | grep "${eth_name}" -A 2)
                LogErr "Additional info for ${eth_name}: ${eth_info}"
                test_result=$(( test_result + 1 ))
            fi
         done

        LogMsg "Sleeping 5 seconds"
        sleep 5
    done


    #####################################################
    # Conclude the result
    if [[ "$test_result" == "0" ]]; then
        SetTestStateCompleted
    else
        SetTestStateFailed
    fi

    LogMsg "*********INFO: Script execution completed. *********"
}

main
exit 0