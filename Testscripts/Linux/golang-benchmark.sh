#!/bin/bash

#######################################################################
#
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
#######################################################################

#######################################################################
#
# golang-benchmark.sh
#
# Description:
# Golang benchmark test
# The binarytree, fasta, fannkuch, mandel, knucleotide, revcomp, nbody,
#     spectralnorm, and pidigits are tested
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

GOLANG_INSTALL_DIR="/usr/local"

Prepare_Test_Dependencies()
{
    LogMsg "Install Dependencies ..."
    wget -t 5 "$GOLANG_BENCHMARK_CODE" -O golang_benchmark.tar.gz -o golang_benchmark.log
    if [ $? -ne 0 ]; then
        LogErr "Get golang benchmark test code from $GOLANG_BENCHMARK_CODE failed"
        SetTestStateAborted
        exit 1
    fi
    tar xvf golang_benchmark.tar.gz

    if [[ "${DISTRO_NAME}" == "debian" ]] || [[ "${DISTRO_NAME}" == "ubuntu" ]] ; then
        dpkg_configure
    fi
    update_repos
    install_package make gcc wget libgmp3-dev
    wget -t 5 "$GOLANG_INSTALL_PACKAGE" -O golang_source.tar.gz -o download_golang.log
    tar xvf golang_source.tar.gz -C "$GOLANG_INSTALL_DIR"
    exit_status=$?
    if [ $exit_status -ne 0 ]; then
        LogErr "Install golang failed"
        SetTestStateAborted
        exit 1
    fi
    export PATH=$PATH:$GOLANG_INSTALL_DIR/go/bin
    LogMsg "Install golang successfully."
}

Parse_Result()
{
    LogMsg "Parse test result ..."
    pushd "${HOME}"/test_results
    csv_file=golangBenchmark.csv
    csv_file_tmp=output_tmp.csv
    rm -rf $csv_file
    echo "Item,UserTime,WallClockTime,CPUUsage,MaximumResidentSetSize,VoluntaryContextSwitches,InvoluntaryContextSwitches,Operations" > $csv_file_tmp
    result_list=($(ls *.result))
    count=0
    while [ "x${result_list[$count]}" != "x" ]
    do
        file_name=${result_list[$count]}
        echo "The file $file_name is parsing ..."
        status=$(grep "Exit status" "$file_name" | tr ":" " " | awk '{print $NF}')
        if [ $status -ne 0 ]; then
            LogMsg "The exit status is $status in $file_name, skip to collect its result"
            ((count++))
            continue
        fi
        Item=$(echo "$file_name" | sed "s/.result//g")
        UserTime=$(grep "User time" "$file_name" | tr ":" " " | awk '{print $NF}')
        WallClockTime=$(grep "Elapsed (wall clock) time" "$file_name" | tr ":" " " | awk '{print $NF}')
        CPUUsage=$(grep "Percent of CPU this job got" "$file_name" | tr ":" " " | awk '{print $NF}')
        MaximumResidentSetSize=$(grep "Maximum resident set size" "$file_name" | tr ":" " " | awk '{print $NF}')
        VoluntaryContextSwitches=$(grep "Voluntary context switches" "$file_name" | tr ":" " " | awk '{print $NF}')
        InvoluntaryContextSwitches=$(grep "Involuntary context switches" "$file_name" | tr ":" " " | awk '{print $NF}')
        Operations=$(grep "ns/op" "$file_name" | awk '{print $3}')
        if [ ! $Operations ]; then
            Operations=0
        fi
        echo "$Item,$UserTime,$WallClockTime,$CPUUsage,$MaximumResidentSetSize,$VoluntaryContextSwitches,$InvoluntaryContextSwitches,$Operations" >> $csv_file_tmp
        ((count++))
    done

    cat $csv_file_tmp > $csv_file
    rm -rf $csv_file_tmp
    LogMsg "Parse test result completed"
    cp $csv_file "$HOME"
    popd
}

Run_Golang_Benchmark_Test()
{
    if [ ! -e ${HOME}/test_results ]; then
        mkdir -p "${HOME}/test_results"
    fi
    pushd golang_benchmark
    declare -A testParameterDic
    testParameterDic=([knucleotide]="knucleotide-input250000.txt" [revcomp]="revcomp-input2500000.txt" 
                      [nbody]="50000000" [spectralnorm]="5500" [pidigits]="10000")
    # Run knucleotide, revcomp, nbody, spectralnorm and pidigits test
    for key in $(echo ${!testParameterDic[*]})
    do
        echo "$key:${testParameterDic[$key]}"
        $GOLANG_INSTALL_DIR/go/bin/go build -o  "$key" "${key}.go"
        outputName="${HOME}/test_results/${key}.result"
        if [ $key == "revcomp" ]; then
            /usr/bin/time --verbose ./${key} 0 < "${testParameterDic[$key]}" &> temp.log
            tail -n 23 temp.log > "$outputName"
        elif [ $key == "knucleotide" ]; then
            /usr/bin/time --verbose ./${key} < "${testParameterDic[$key]}" &> "$outputName"
        else
            /usr/bin/time --verbose ./${key} "${testParameterDic[$key]}" &> "$outputName"
        fi
    done
    popd

    # Run binarytree, fasta, fannkuch and mandel test.
    # They are provided by default when the golang is installed.
    pushd $GOLANG_INSTALL_DIR/go/test/bench/go1/
    testList="binarytree fasta fannkuch mandel"
    for testName in $testList; do 
        outputName="${HOME}/test_results/${testName}.result"
        /usr/bin/time -v go test -bench=. "${testName}_test".go &> "$outputName"
    done
    popd
}

collect_VM_properties
Prepare_Test_Dependencies
LogMsg "*********INFO: Starting test execution*********"
SetTestStateRunning
#Collect the go version
echo ",Go Version,$($GOLANG_INSTALL_DIR/go/bin/go version)" >> VM_properties.csv
Run_Golang_Benchmark_Test
Parse_Result
tar czf test_results.tar.gz ${HOME}/test_results
SetTestStateCompleted
