#!/bin/bash -x

tdir=$1
src_disk=$2
tgt_disk=$3
FAILED_TEST=1
PASSED_TEST=0
dmesg_log_file="$tdir/dmesg.log"
log()
{
    echo "$(date):[cvt] -> $*" | tee -a "$tdir/cvt.log"
}

log_dmesg()
{
    dmesg -c > "$dmesg_log_file"
    if [ -z "$dmesg_log_file" ]; then
        echo "<This file is intentionally empty>" > "$dmesg_log_file"
    fi
}

exit_with_retcode()
{
    echo "TEST_STATUS:$1"
    exit "$1"
}

get_testname()
{
    TESTNAME="barrierhonourwithouttag"
    local curr_kernel, major_ver, minor_ver
    curr_kernel=$(uname -r)
    major_ver=$(echo "$curr_kernel" | cut -f1 -d'.')
    minor_ver=$(echo "$curr_kernel" | cut -f2 -d'.')

    if [ "$major_ver" -gt 5 ]; then
       return
    fi
    if [ "$major_ver" -eq 5 ] && [ "$minor_ver" -ge 8 ]; then
       return
    fi

    TESTNAME="ditest"
    if [ -f /etc/os-release ] && grep -q 'SLES' /etc/os-release; then
        if grep -q 'VERSION="15-SP3' /etc/os-release; then
            TESTNAME="barrierhonourwithouttag"
        fi
    fi
}

set_test_params()
{
    local timeout

    log "Setting test params"
    timeout=60000
    get_testname
    if [ "$TESTNAME" = "barrierhonourwithouttag" ]; then
        timeout=600000
    fi

    /usr/local/ASR/Vx/bin/inm_dmit --set_attr VacpIObarrierTimeout $timeout || {
        log_dmesg
        exit_with_retcode $FAILED_TEST
    }

    /usr/local/ASR/Vx/bin/inm_dmit --set_attr DirtyBlockHighWaterMarkServiceRunning 30000 || {
        log_dmesg
        exit_with_retcode $FAILED_TEST
    }

    return 0
}

execute_cmd()
{
    local cmd="$1"
    local dont_exit_on_fail=0

    if [[ -n "$2" ]]; then
        dont_exit_on_fail=1
    fi

    echo "Executing command: $cmd"
    eval "$cmd"
    local funret=$?
    if [[ $funret != 0 ]]; then
        printf 'command: %s failed with return value %d\n' "$cmd" "$funret"
        if [[ $dont_exit_on_fail == 0 ]]; then
            return 1;
        fi
    fi
}

startcvt()
{

    if [[ $# -ne 4 ]]; then
        echo "Insufficient number of args"
        return 1
    fi

    local source_dev, target_dir, subtestname, testname
    local workingdir, cvt_logs_dir, cvt_log_file, cvt_op_file
    local lsmodop, grepop
    source_dev=$1
    target_dir=$2
    subtestname=$3
    testname=$4
    workingdir=$PWD
    cvt_logs_dir="$workingdir/cvt_logs"
    cvt_log_file="$cvt_logs_dir/cvtlog_$subtestname.txt"
    cvt_op_file="$cvt_logs_dir/cvt_$subtestname.txt"


    lsmodop=$(lsmod | grep "involflt")
    if [[ -z "${lsmodop// }" ]]; then
        echo "Driver not loaded, exiting"
        return 1
    fi

    if [[ ! -e $target_dir ]]; then
        echo "Target directory $target_dir doesn't exist"
        return 1
    fi

    if [[ ! -e $source_dev ]]; then
        echo "Source dev $source_dev doesn't exist"
        return 1
    fi

    if [ "$testname" = "ditest" ]; then
        sourcedevsize=$(blockdev --getsize64 "$source_dev")
        if [[ "$sourcedevsize" -gt 2147483648 ]]; then
            echo "Source dev $source_dev size is $sourcedevsize"
            echo "CVT works on source dev of size <= 2GB"
            return 1
        fi
    fi

    /usr/local/ASR/Vx/bin/stop
    execute_cmd "mkdir -p $cvt_logs_dir"

    chmod +x "$workingdir/indskflt_ct"
    /usr/local/ASR/Vx/bin/inm_dmit --op=start_notify&
    execute_cmd "time $workingdir/indskflt_ct --tc=$testname --loggerPath=$cvt_logs_dir --pair[ -type=d-f -sd=$source_dev -td=$target_dir/target_file.tgt -subtest=$subtestname -log=$cvt_log_file ] >> $cvt_op_file 2>&1" "ignorefail"
    killall inm_dmit
    pkill inm_dmit

    grepop=$(grep -i "DI Test Passed" < "$cvt_op_file")
    if [[ -z "${grepop// }" ]]; then
            echo "CVT test failed"
            mv "$cvt_log_file" "$cvt_log_file"."$(date)"
            mv "$cvt_op_file" "$cvt_op_file"."$(date)"
            return "$FAILED_TEST"
    else
            echo "CVT test passed"
            return "$PASSED_TEST"
    fi

}

run_tests()
{
    local failed, stime, ctests, ntests
    local diskname, testcases, curdir
    failed=0
    stime=10
    ctests=0
    mnt_path="/data"
    umount $mnt_path
    diskname=$tgt_disk
    log "Formatting Disk"
    yes | mkfs "$diskname"
    log "Mounting $diskname to $mnt_path"
    mkdir $mnt_path > /dev/null 2>&1
    mount "$diskname" "$mnt_path"

    testcases=('mixed' '16k_random' '16k_seq' '1mb_random' '1mb_seq' '4k_random' '4k_seq' '4mb_random' '4mb_seq' '512k_random' '512k_seq' '64k_random' '64k_seq' '8mb_random' '8mb_seq' '9mb_random' '9mb_seq')
    ntests=${#testcases[@]}
    log "Total Tests: $ntests"

    curdir=$(pwd)
    cd "$tdir" || exit_with_retcode "$FAILED_TEST"
    for testcase in "${testcases[@]}"; do
        echo -e "$ctests/$ntests\r"
        log "Starting $testcase test"
        startcvt "$src_disk" "$mnt_path" "$testcase" "$TESTNAME" > "$tdir"/"$testcase".log 2>&1
        failed=$?
        if [[ $failed != 0 ]]; then
            sleep $stime
            # might have failed to take barrier, retry
            startcvt "$src_disk" "$mnt_path" "$testcase" "$TESTNAME" > "$tdir"/"$testcase".log 2>&1
            failed=$?
        fi
        ((ctests++))

        if [ $failed -eq 1 ]; then
            log_dmesg
            exit_with_retcode "$FAILED_TEST"
        fi

        sleep $stime
    done

    cd "$curdir" || exit_with_retcode "$FAILED_TEST"
    return "$failed"
}

set_test_params
run_tests
exit_with_retcode $?