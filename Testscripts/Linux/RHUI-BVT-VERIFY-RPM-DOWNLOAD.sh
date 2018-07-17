#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
./package-download-test.sh
if [[ $? == 0 ]]; then
        echo 'PASS' > Summary.log
else
        echo 'FAIL' > Summary.log
fi
echo 'TestCompleted' > state.txt