#!/bin/bash
########################################################################
#
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
# Description:
# Script to run the hello-world java app in docker.
#
########################################################################

DOCKER_FILENAME="Dockerfile"

JAVA_PROG_APP="Main"
JAVA_PROG_SRC="Main.java"

CONTAINER_NAME="javaapp"
CONTAINER_IMAGE_NAME="javaappimage"

STRING_IDENTIFIER="Hello world from java"

# Function to generate java program which will run
# inside docker
GenerateJavaProgram() {
cat << EOF > $JAVA_PROG_SRC
public class Main
{
    public static void main(String[] args) {
        System.out.println("$STRING_IDENTIFIER");
    }
}
EOF
    [[ ! -f $JAVA_PROG_SRC ]] && return 1
    return 0
}

# Function to generate docker file
GenerateDockerFile() {
cat << EOF > $DOCKER_FILENAME
FROM alpine

WORKDIR /usr/src/myapp
COPY ${JAVA_PROG_SRC} /usr/src/myapp

#install jdk
RUN apk add openjdk8
ENV JAVA_HOME /usr/lib/jvm/java-1.8-openjdk
ENV PATH \$PATH:\$JAVA_HOME/bin

#compile program
RUN javac ${JAVA_PROG_SRC}

ENTRYPOINT java ${JAVA_PROG_APP}
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
    echo "ERROR: unable to source containers_utils.sh"
    echo "TestAborted" > state.txt
    exit 0
}

UtilsInit

GetDistro
update_repos

InstallDockerEngine; ret=$?
[[ $ret -ne 0 ]] && HandleFailure "ERROR: InstallDockerEngine" "$ret"

RemoveDockerContainer $CONTAINER_NAME
RemoveDockerImage $CONTAINER_IMAGE_NAME

GenerateJavaProgram; ret=$?
[[ $ret -ne 0 ]] && HandleAbort "ERROR: GenerateJavaProgram" "$ret"

GenerateDockerFile; ret=$?
[[ $ret -ne 0 ]] && HandleAbort "ERROR: GenerateDockerFile" "$ret"

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
