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
#   This script installs Docker Compose.
#
# Steps:
#
########################################################################
function install_docker_compose() {
	LogMsg "Download the current stable release of Docker Compose"
	curl -L "https://github.com/docker/compose/releases/download/1.25.4/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
	chmod +x /usr/local/bin/docker-compose
	ln -s /usr/local/bin/docker-compose /usr/bin/docker-compose
	docker-compose --version
	if [ $? -ne 0 ]; then
		LogErr "Fail to install docker-compose."
		SetTestStateFailed
		exit 1
	fi
}

function compose_and_wordpress() {
	mkdir wordpress
	pushd wordpress
	cat <<-EOF > "docker-compose.yml"
version: '3.3'

services:
   db:
     image: mysql:5.7
     volumes:
       - db_data:/var/lib/mysql
     restart: always
     environment:
       MYSQL_ROOT_PASSWORD: somewordpress
       MYSQL_DATABASE: wordpress
       MYSQL_USER: wordpress
       MYSQL_PASSWORD: wordpress

   wordpress:
     depends_on:
       - db
     image: wordpress:latest
     ports:
       - "80:80"
     restart: always
     environment:
       WORDPRESS_DB_HOST: db:3306
       WORDPRESS_DB_USER: wordpress
       WORDPRESS_DB_PASSWORD: wordpress
       WORDPRESS_DB_NAME: wordpress
volumes:
    db_data: {}
EOF
	LogMsg "Run docker-compose up -d."
	docker-compose up -d
	LogMsg "Run docker-compose ps."
	docker-compose ps
	popd
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
install_docker_compose
compose_and_wordpress
SetTestStateCompleted
exit 0
