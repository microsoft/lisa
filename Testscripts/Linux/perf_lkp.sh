#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

###############################################################################
#
# Description:
# Support distros: Ubuntu 18.04 
#
###############################################################################

LKP_SCHEDULER_HACKBENCH_TESTS=("hackbench-100.yaml" "hackbench.yaml")
LKP_SCHEDULER_PERF_BENCH_SCHED_PIPE_TESTS=("perf-bench-sched-pipe.yaml")
LKP_SCHEDULER_SCHBENCH_TESTS=("schbench.yaml")
LKP_DATABASE_OLTP_TESTS=("oltp.yaml")
LKP_DATABASE_REDIS_TESTS=("redis.yaml")
LKP_MEMORY_PERF_BENCH_NUMA_MEM_TESTS=("perf-bench-numa-mem.yaml")
LKP_MEMORY_PMBENCH_TESTS=("pmbench.yaml")
LKP_WORKLOAD_APACHEBENCH_TESTS=("apachebench.yaml")
LKP_TESTS_ALL_ABOVE=("perf-bench-sched-pipe.yaml" "schbench.yaml" "oltp.yaml" "redis.yaml" \
                     "perf-bench-numa-mem.yaml" "pmbench.yaml" "apachebench.yaml")
LKP_OTHER_UNIXBENCH_TESTS=("unixbench.yaml")
LKP_OTHER_AIM9_TESTS=("aim9.yaml")

###############################################################################
function install_dependencies() {
    LogMsg "Installing dependency packages"

    GetDistro
    update_repos

    case $DISTRO in
        ubuntu* | debian*)
            CheckInstallLockUbuntu
            deb_packages=(make git)
            LogMsg "Dependency package names： ${deb_packages[@]}"
            install_package "${deb_packages[@]}" >> $LKP_OUTPUT 2>&1
            ;;
        centos_7 | redhat_7)
            rpm_packages=(make git curl psmisc)
            install_epel
            LogMsg "Dependency package names： ${rpm_packages[@]}"
            install_package "${rpm_packages[@]}" >> $LKP_OUTPUT 2>&1
            gpg --keyserver hkp://keys.gnupg.net --recv-keys 409B6B1796C275462A1703113804BB82D39DC0E3 7D2BAF1CF37B13E2069D6956105BD0E739499BDB
            curl -sSL https://get.rvm.io | bash -s stable
            if [ $? -ne 0 ]; then
                LogErr "Failed to curl rvm"
                SetTestStateAborted
                exit 1
            fi
            source /etc/profile.d/rvm.sh
            rvm requirements
            rvm install ruby-2.3.0
            rvm use ruby-2.3.0 default
            PATH="$PATH:/usr/local/bin"
            ;;
        *)
            LogErr "Unsupported distro: $DISTRO"
            return 1
            ;;
    esac
}

function choose_test_case {
    TEST_NAME_SET=("$TEST_NAME")
    case $TEST_NAME in
        hackbench)
            LKP_TESTS=${LKP_SCHEDULER_HACKBENCH_TESTS[@]}
            ;;
        perf-bench-sched-pipe)
            LKP_TESTS=${LKP_SCHEDULER_PERF_BENCH_SCHED_PIPE_TESTS[@]}
            ;;
        schbench)
            LKP_TESTS=${LKP_SCHEDULER_SCHBENCH_TESTS[@]}
            ;;
        oltp)
            LKP_TESTS=${LKP_DATABASE_OLTP_TESTS[@]}
            ;;
        redis)
            LKP_TESTS=${LKP_DATABASE_REDIS_TESTS[@]}
            ;;
        perf-bench-numa-mem)
            LKP_TESTS=${LKP_MEMORY_PERF_BENCH_NUMA_MEM_TESTS[@]}
            ;;
        pmbench)
            LKP_TESTS=${LKP_MEMORY_PMBENCH_TESTS[@]}
            ;;
        apachebench)
            LKP_TESTS=${LKP_WORKLOAD_APACHEBENCH_TESTS[@]}
            ;;
        unixbench)
            LKP_TESTS=${LKP_OTHER_UNIXBENCH_TESTS[@]}
            ;;
        aim9)
            LKP_TESTS=${LKP_OTHER_AIM9_TESTS[@]}
            ;;
        lkp_microbenchmark)
            LKP_TESTS=${LKP_TESTS_ALL_ABOVE[@]}
            TEST_NAME_SET=("perf-bench-sched-pipe" "schbench" "oltp" "redis" \
                           "perf-bench-numa-mem" "pmbench" "apachebench")
            ;;
        *)
            LogErr "Unsupported test case: $TEST_NAME"
            return 1
            ;;
    esac
    for test in ${LKP_TESTS[@]}; do
        LogMsg "Choose test case: $test"
    done
}

function run_tests {
    LogMsg "git clone LKP..."
    if [[ $DISTRO =~ "redhat" ]]; then
        work_dir=$(df -h | grep "/dev/sdb1" | awk -F " " '{ print $6 }')
        cd "$work_dir"
    fi

    git clone https://github.com/intel/lkp-tests.git
    cd lkp-tests
    make install
    if [[ $? -ne 0 ]];then
        LogErr "LKP make failed"
        SetTestStateAborted
        exit 1
    fi

    LogMsg "install LKP..."
    yes | lkp install >> $LKP_OUTPUT 2>&1
    if [[ $? -ne 0 ]];then
        LogErr "LKP install failed"
        SetTestStateAborted
        exit 1
    fi

    LogMsg "split job..."
    for test in ${LKP_TESTS[@]}; do
        lkp split-job jobs/$test >> $LKP_OUTPUT 2>&1
    done

    LogMsg "install and run job..."
    for testName in ${TEST_NAME_SET[@]}; do
        lkp install $(ls $testName-* | head -n1) >> $LKP_OUTPUT 2>&1
        if [[ $TEST_NAME =~ "aim9" ]]; then
            all_jobs=$(ls aim9-all-*.yaml)
        else
            all_jobs=$(ls | grep $testName)
        fi
        for job in $all_jobs; do
            LogMsg "run job $job..."
            lkp run $job >> $LKP_OUTPUT 2>&1
            if [[ $? -ne 0 ]];then
                LogErr "LKP $job test failed"
            fi
        done
        results="$(lkp result $testName)"

        LogMsg "collect results..."
        for result in $results; do
            job_name=$(echo $result | awk -F "/" '{ print $5 }')
            LKP_TEST_LOG="$LKP_LOG_DIR/$testName/$job_name"
            mkdir -p "$LKP_TEST_LOG"
            if [ -d "$result" ]; then 
                LogMsg "copy result log to $LKP_TEST_LOG..."
                cp $result* $LKP_TEST_LOG
            else
                LogErr "$result doesn't exist"
            fi
        done
    done

    cd $HOMEDIR
    tar -cvf "lkp_log.tar" lkp_log
}
###############################################################################
#
# Main script body
#
###############################################################################
# Source utils.sh
. utils.sh || {
    echo "unable to source utils.sh!"
    echo "TestAborted" > state.txt
    exit 2
}
# Source constants file and initialize most common variables
UtilsInit

HOMEDIR=$(pwd)
LKP_OUTPUT="$HOMEDIR/lkp-output.log"
LKP_LOG_DIR="$HOMEDIR/lkp_log"

mkdir -p $LKP_LOG_DIR
if [ $? -ne 0 ]; then
    LogErr "Failed to mkdir -p $LKP_LOG_DIR"
    SetTestStateAborted
    exit 1
fi

LogMsg "Installing dependencies"
install_dependencies
if [ $? -ne 0 ]; then
    LogErr "Failed to install dependency packages"
    SetTestStateSkipped
    exit 1
fi

LogMsg "Choose test case..."
choose_test_case
if [ $? -ne 0 ]; then
    LogErr "Test name error"
    SetTestStateAborted
    exit 1
fi

LogMsg "Run LKP tests"
run_tests

SetTestStateCompleted
exit 0







