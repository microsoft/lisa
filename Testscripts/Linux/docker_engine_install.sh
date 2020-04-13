#!/bin/bash
########################################################################
#
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
########################################################################
########################################################################
#
# Description:
#   This script installs Docker Engine.
#
# Steps:
#
########################################################################
function verify_docker_engine() {
	LogMsg "verify_docker_engine on $DISTRO"

	output=$(docker run hello-world)
	if [ $? -ne 0 ]; then
		LogErr "Fail to run docker run hello-world"
		SetTestStateFailed
		exit 1
	fi
	LogMsg "verify_docker_engine - $output"
}

function install_docker_engine() {
	LogMsg "install_docker_engine on $DISTRO"

	case $DISTRO in
		ubuntu*|debian*)
			LogMsg "Install the latest version of Docker Engine and containerd"
			apt-get update
			install_package "docker-ce docker-ce-cli containerd.io"
		;;

		centos*|redhat*)
			LogMsg "Install packages docker-ce docker-ce-cli containerd.io."
			yum install --nogpgcheck -y docker-ce docker-ce-cli containerd.io --nobest
			LogMsg "Start docker service."
			systemctl start docker || service docker start
			if [ $? -ne 0 ]; then
				LogErr "Fail to start docker service."
				SetTestStateFailed
				exit 1
			fi
		;;
	esac
}

function install_docker_engine_requirements() {
	LogMsg "install_docker_engine_requirements on $DISTRO"

	case $DISTRO in
		ubuntu*|debian*)
			LogMsg "Uninstall old versions of Docker."
			apt-get remove -y docker docker-engine docker.io containerd runc
			LogMsg "Install packages apt-transport-https ca-certificates curl gnupg-agent software-properties-common."
			apt-get update
			install_package "apt-transport-https ca-certificates curl gnupg-agent software-properties-common"
			LogMsg "Add Docker's official GPG key."
			curl -fsSL https://download.docker.com/linux/$DISTRO_NAME/gpg | sudo apt-key add -
			LogMsg "Set up the stable repository."
			add-apt-repository "deb [arch=amd64] https://download.docker.com/linux/$DISTRO_NAME $(lsb_release -cs) stable"
		;;

		centos*|redhat*)
			LogMsg "Uninstall old versions of Docker."
			yum remove docker docker-client docker-client-latest docker-common docker-latest docker-latest-logrotate docker-logrotate docker-engine
			LogMsg "Install package yum-utils."
			install_package "yum-utils"
			LogMsg "Add repo https://download.docker.com/linux/centos/docker-ce.repo."
			yum-config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
		;;
	esac
}

#######################################################################
#
# Main script body
#
#######################################################################
# Source utils.sh
. utils.sh || {
    echo "ERROR: unable to source utils.sh!"
    echo "TestAborted" > state.txt
    exit 0
}
UtilsInit

GetDistro
update_repos
#skip_test
install_docker_engine_requirements
install_docker_engine
verify_docker_engine
SetTestStateCompleted
exit 0
