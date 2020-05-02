#!/bin/bash
########################################################################
#
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
# Description:
# Script to run the hello-world python app in docker.
#
########################################################################

DOCKER_FILENAME="Dockerfile"

PYTHON_PROG_NAME="helloworld.py"

CONTAINER_NAME="pythonapp"
CONTAINER_IMAGE_NAME="pythonappimage"

STRING_IDENTIFIER="Hello world from python"

# Function to generate python program which will run
# inside docker
GeneratePythonProgram() {
cat << EOF > $PYTHON_PROG_NAME
print("$STRING_IDENTIFIER")
EOF
    [[ ! -f $PYTHON_PROG_NAME ]] && return 1
    return 0
}

# Function to generate docker file
GenerateDockerFile() {
cat << EOF > $DOCKER_FILENAME
FROM ubuntu:18.04

RUN apt-get update && apt-get install python3 -y
COPY $PYTHON_PROG_NAME /
ENTRYPOINT ["python3"]
CMD ["/$PYTHON_PROG_NAME"]
EOF
    [[ ! -f $DOCKER_FILENAME ]] && return 1
    return 0
}

# Function to evaluate the test results
EvaluateTestResult() {
    grep -qw "${STRING_IDENTIFIER}" $DOCKER_RUN_OUTPUT && return 0
    return 1
}

#######################################################################
#
# Main script body
#
#######################################################################

# Source containers_utils.sh
. containers_utils.sh || {
    echo "ERROR: unable to source utils.sh!"
    echo "TestAborted" > state.txt
    exit 0
}

UtilsInit

GetDistro
update_repos

InstallDockerEngine; ret=$?
[[ $ret -ne 0 ]] && HandleFailure "ERROR: InstallDockerEngine" "$ret"

GeneratePythonProgram; ret=$?
[[ $ret -ne 0 ]] && HandleAbort "ERROR: GeneratePythonProgram" "$ret"

GenerateDockerFile; ret=$?
[[ $ret -ne 0 ]] && HandleAbort "ERROR: GenerateDockerFile" "$ret"

RemoveDockerContainer $CONTAINER_NAME
RemoveDockerImage $CONTAINER_IMAGE_NAME

BuildDockerImage $CONTAINER_IMAGE_NAME; ret=$?
LogMsg "$(cat $DOCKER_BUILD_OUTPUT)"
[[ $ret -ne 0 ]] && HandleFailure "ERROR: BuildDockerImage" "$ret"

RunDockerContainer $CONTAINER_IMAGE_NAME $CONTAINER_NAME; ret=$?
LogMsg "$(cat $DOCKER_RUN_OUTPUT)"
[[ $ret -ne 0 ]] && HandleFailure "ERROR: RunDockerContainer" "$ret"

EvaluateTestResult; ret=$?
[[ $ret -ne 0 ]] && HandleFailure "ERROR: EvaluateTestResult" "$ret"

SetTestStateCompleted
exit 0
