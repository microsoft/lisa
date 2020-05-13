#!/bin/bash
########################################################################
#
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
# Description:
# Script to compile and run the dotnet hello-world app in docker.
#
########################################################################

DOCKER_FILENAME="Dockerfile"

CONTAINER_NAME="dotnetapp"
CONTAINER_IMAGE_NAME="dotnetimage"

STRING_IDENTIFIER="Hello World"

# Function to check the Dotnet package support
CheckDotnetSDKSupport() {
    local package_name=$1
    [[ -z $package_name ]] && return 1

    curl --head --silent --fail $package_name
    local status=$?
    if [[ $status -ne 0 ]];then
        echo "$package_name not available"
       return 1
    fi
    return 0
}

# Function to install Dotnet SDK
InstallDotnetSDK() {
    local ret=0
    distro=$(cat /etc/os-release | grep -w "ID" | cut -d= -f2 | tr -d \")
    id=$(cat /etc/os-release | grep -w "VERSION_ID=" | cut -d= -f2 | tr -d \")
    package_name="packages-microsoft-prod"

    case $DISTRO in
        ubuntu*|debian*)
            package_name=${package_name}.deb
            package=https://packages.microsoft.com/config/${distro}/${id}/${package_name}
            if CheckDotnetSDKSupport $package;then
                wget ${package} -O ${package_name}
                dpkg -i ${package_name}
                add-apt-repository universe
                apt-get update
                apt-get install apt-transport-https
                apt-get update
                apt-get install -y dotnet-sdk-3.1
                ret=$?
            else
                ret=2
            fi
        ;;

        centos*|redhat*)
            package_name=${package_name}.rpm
            package=https://packages.microsoft.com/config/${distro}/${id}/${package_name}
            if CheckDotnetSDKSupport $package;then
                rpm -ivh ${package}
                yum install -y dotnet-sdk-3.1
                ret=$?
            else
                ret=2
            fi

        ;;

        *)
            LogErr "$DISTRO not supported"
            ret=2
    esac

    return $ret
}

# Function to compile dotnet application
CompileDotnetApplication() {
    APP_FOLDER="app"
    [[ -d ${APP_FOLDER} ]] && rm -rf ${APP_FOLDER}

    dotnet new console -o app -n helloworld
    if [[ $? -ne 0 ]];then
        echo "Failed to compile dotnet application"
        return 1
    fi

    pushd ${APP_FOLDER}
    dotnet run
    dotnet publish -c Release
    popd
}

# Function to generate docker file
GenerateDockerFile() {
cat << EOF > $DOCKER_FILENAME
FROM mcr.microsoft.com/dotnet/core/sdk:3.1

COPY app/bin/Release/netcoreapp3.1/publish/ app/
WORKDIR /app

ENTRYPOINT ["dotnet", "helloworld.dll"]
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
[[ $ret -ne 0 ]] && HandleFailure "ERROR: InstallDockerEngine failed" "$ret"

InstallDotnetSDK; ret=$?
[[ $ret -eq 2 ]] && HandleSkip "WARN: InstallDotnetSDK failed" "$ret"
[[ $ret -ne 0 ]] && HandleAbort "ERROR: InstallDotnetSDK failed" "$ret"

CompileDotnetApplication; ret=$?
[[ $ret -ne 0 ]] && HandleAbort "ERROR: CompileDotnetApplication failed" "$ret"

GenerateDockerFile; ret=$?
[[ $ret -ne 0 ]] && HandleAbort "ERROR: GenerateDockerFile failed" "$ret"

RemoveDockerContainer $CONTAINER_NAME
RemoveDockerImage $CONTAINER_IMAGE_NAME

BuildDockerImage $CONTAINER_IMAGE_NAME; ret=$?
[[ $ret -ne 0 ]] && HandleFailure "ERROR: BuildDockerImage failed" "$ret"

RunDockerContainer $CONTAINER_IMAGE_NAME $CONTAINER_NAME; ret=$?
[[ $ret -ne 0 ]] && HandleFailure "ERROR: RunDockerContainer failed" "$ret"

EvaluateTestResult; ret=$?
[[ $ret -ne 0 ]] && HandleFailure "ERROR: EvaluateTestResult failed" "$ret"

SetTestStateCompleted
exit 0
