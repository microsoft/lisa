#!/bin/bash

# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
# Description:
# Functional NVME test script that checks if commands that are
# expected to fail do so. The current commands that are expected
# to fail are creating, deleting and detaching a namespace.
######################################################################
expected_fail_cmd_list=("create-ns" "delete-ns -n 1" "detach-ns -n 1")
. utils.sh || {
    echo "ERROR: unable to source utils.sh!"
    echo "TestAborted" > state.txt
    exit 0
}
UtilsInit

# Install nvme-cli tool
update_repos
install_nvme_cli

# Count NVME namespaces
namespace_count=$(ls -l /dev | grep -w nvme[0-9]n[0-9]$ | awk '{print $10}' | wc -l)
if [ "$namespace_count" -eq "0" ]; then
    LogErr "No NVME namespaces detected inside the VM"
    SetTestStateFailed
    exit 0
fi

# Check namespaces in nvme cli
namespace_list=$(ls -l /dev | grep -w nvme[0-9]n[0-9]$ | awk '{print $10}')
for namespace in ${namespace_list}; do
    # Run every command from the list. All of them should fail
    # The list 'expected_fail_cmd_list' can be expanded if required
    for nvme_cmd in "${expected_fail_cmd_list[@]}"; do
        nvme $nvme_cmd /dev/"$namespace"
        if [ $? -eq 0 ]; then
            LogErr "The command 'nvme ${nvme_cmd} $namespace' should have failed!"
            SetTestStateFailed
            exit 0
        fi
    done
    UpdateSummary "All the commands on ${namespace} failed as expected!"
done

# All the operations succeeded and the test is complete
SetTestStateCompleted
exit 0