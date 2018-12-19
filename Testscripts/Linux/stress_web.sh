#!/bin/bash

#######################################################################
#
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
#######################################################################

#######################################################################
#
# stress_web.sh
#
# Description:
# http_load runs multiple http fetches in parallel, to test the
# throughput of a web server.
#
# Dependency:
#   utils.sh
#######################################################################

. utils.sh || {
    echo "Error: missing utils.sh file"
    echo "TestAborted" > "${HOME}"/state.txt
    exit 1
}

# Source constants file and initialize most common variables
UtilsInit

Prepare_Test_Dependencies()
{
    LogMsg "Install http_load ..."
    if [[ "${DISTRO_NAME}" == "debian" ]] || [[ "${DISTRO_NAME}" == "ubuntu" ]] ; then
        dpkg_configure
    fi
    update_repos
    install_package make gcc wget
    wget -t 5 "$HTTP_LOAD" -O http_load_source.tar.gz -o download_http_load.log
    mkdir http_load_source
    tar zxvf http_load_source.tar.gz -C http_load_source
    pushd http_load_source/http_load*
    make && make install
    exit_status=$?
    if [ $exit_status -ne 0 ]; then
        LogErr "Install http_load failed"
        SetTestStateAborted
        exit 1
    fi
    popd
    LogMsg "Install http_load successfully."
}

Parse_Result()
{
    LogMsg "Parse test result ..."
    csv_file=nginxStress.csv
    csv_file_tmp=output_tmp.csv
    rm -rf $csv_file
    echo "fetches,max_parallel,fetches_per_sec,msecs_per_connec,seconds,success_fetches" > $csv_file_tmp

    result_list=($(ls *.http_load.result))
    count=0
    while [ "x${result_list[$count]}" != "x" ]
    do
        file_name=${result_list[$count]}
        echo "The file $file_name is parsing ..."
        fetches=$(grep "fetches," "$file_name" | awk '{print $1}')
        max_parallel=$(grep "max parallel" "$file_name" | awk '{print $3}')
        fetches_per_sec=$(grep "fetches/sec" "$file_name" | awk '{print $1}')
        msecs_per_connec=$(grep "msecs/connect:" "$file_name" | awk '{print $2}')
        seconds=$(grep "seconds$" "$file_name" | awk -F ',' '{print $4}' | awk '{print $2}')
        success_fetches=$(grep "code 200" "$file_name" | awk '{print $4}')

        echo "$fetches,$max_parallel,$fetches_per_sec,$msecs_per_connec,$seconds,$success_fetches" >> $csv_file_tmp
        ((count++))
    done

    cat $csv_file_tmp > $csv_file
    rm -rf $csv_file_tmp
    LogMsg "Parse test result completed"
    cp $csv_file "$HOME"
}

Run_Web_Test()
{
    iteration=0
    mkdir -p "${HOME}"/web_test_results
    for parallel in $parallelConnections; do
        outputName="${HOME}/web_test_results/web-${parallel}th-${runtime}s.http_load.result"
        LogMsg "-- iteration ${iteration} -- ${parallel} parallel connections, ${runtime} seconds -- $(date +"%x %r %Z") --"
        http_load -p "${parallel}" -s "${runtime}" "${HOME}"/urls  >> "$outputName"
        exit_status=$?
        if [ $exit_status -ne 0 ]; then
            LogErr "Run http_load -p ${parallel} -s ${runtime} ${HOME}/urls  failed"
            SetTestStateFailed
            exit 1
        fi
        iteration=$(( iteration+1 ))
    done
}

collect_VM_properties
Prepare_Test_Dependencies
LogMsg "*********INFO: Starting test execution*********"
SetTestStateRunning
Run_Web_Test
cd "${HOME}"/web_test_results
Parse_Result
cd "$HOME"
tar czf web_test_results.tar.gz web_test_results/
SetTestStateCompleted
