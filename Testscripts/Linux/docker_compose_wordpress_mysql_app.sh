#!/bin/bash
########################################################################
#
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
# Description:
#   This script run wordpress application using docker compose.
#
########################################################################

CONTAINER_NAME="wordpress_ex"

function RunDockerCompose() {
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
     container_name: ${CONTAINER_NAME}
     ports:
       - "8080:80"
     restart: always
     environment:
       WORDPRESS_DB_HOST: db:3306
       WORDPRESS_DB_USER: wordpress
       WORDPRESS_DB_PASSWORD: wordpress
       WORDPRESS_DB_NAME: wordpress
volumes:
    db_data: {}
EOF
    LogMsg "Run docker-compose up in detached mode"
    docker-compose up -d; ret=$?
    popd
    return $ret
}

# Function to evaluate the test result
function EvaluateTestResult() {
    # Make sure that the container is running and apache websever is started
    local cnt=0
    local ret=1
    while true; do
        out=$(docker exec ${CONTAINER_NAME} ps ax | grep apache2); ret=$?
        LogMsg "EvaluateTestResult: $out"
        [[ $ret -eq 0 ]] && return $ret

        # Try for 60 seconds to check the apache webserver status
        [[ $cnt -ge 60 ]] && break

        cnt=$((cnt+1))
        LogMsg "EvaluateTestResult: sleep 1 second count: $cnt"
        sleep 1
    done
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
update_repos

InstallDockerEngine; ret=$?
[[ $ret -ne 0 ]] && HandleFailure "ERROR: InstallDockerEngine failed" "$ret"

InstallDockerCompose; ret=$?
[[ $ret -ne 0 ]] && HandleFailure "ERROR: InstallDockerCompose" "$ret"

RunDockerCompose; ret=$?
[[ $ret -ne 0 ]] && HandleFailure "ERROR: RunDockerCompose failed" "$ret"

EvaluateTestResult; ret=$?
[[ $ret -ne 0 ]] && HandleFailure "ERROR: EvaluateTestResult failed" "$ret"

SetTestStateCompleted
exit 0
