#!/bin/bash -x

tdir=$1
PASSED_TEST=0
FAILED_TEST=1
log()
{
    echo "`date`:[cvt] -> $*" | tee -a $tdir/cvt.log
}

exit_with_logs()
{
    echo "TEST_STATUS:$1:$2"
    exit $1
}

get_testname()
{
    TESTNAME="barrierhonourwithouttag"
    local curr_kernel=`uname -r`
    local major_ver=`echo $curr_kernel | cut -f1 -d'.'`
    local minor_ver=`echo $curr_kernel | cut -f2 -d'.'`

    if [ $major_ver -gt 5 ]; then
       return
    fi
    if [ $major_ver -eq 5 -a $minor_ver -ge 8 ]; then
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
    local _ret=

    log "Setting test params"
    local timeout=60000
    get_testname
    if [ "$TESTNAME" = "barrierhonourwithouttag" ]; then
        timeout=600000
    fi

    /usr/local/ASR/Vx/bin/inm_dmit --set_attr VacpIObarrierTimeout $timeout || {
        log_dmesg
        exit_with_logs $FAILED_TEST /tmp/dmesg.log
    }

    /usr/local/ASR/Vx/bin/inm_dmit --set_attr DirtyBlockHighWaterMarkServiceRunning 30000 || {
        log_dmesg
        exit_with_logs $FAILED_TEST /tmp/dmesg.log
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
    #op=$($cmd)
    eval $cmd
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

    local source_dev=$1
    local target_dir=$2
    local subtestname=$3
    local testname=$4

    local workingdir=$PWD
    local cvt_logs_dir="$workingdir/cvt_logs"
    local cvt_log_file="$cvt_logs_dir/cvtlog_$subtestname.txt"
    local cvt_op_file="$cvt_logs_dir/cvt_$subtestname.txt"


    local lsmodop=$(lsmod | grep "involflt")
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

    if [ $testname = "ditest" ]; then
        sourcedevsize=`blockdev --getsize64 $source_dev`
        if [[ $sourcedevsize -gt 2147483648 ]]; then
            echo "Source dev $source_dev size is $sourcedevsize"
            echo "CVT works on source dev of size <= 2GB"
            return 1
        fi
    fi

    /usr/local/ASR/Vx/bin/stop
    execute_cmd "mkdir -p $cvt_logs_dir"

    chmod +x $workingdir/indskflt_ct
    /usr/local/ASR/Vx/bin/inm_dmit --op=start_notify&
    execute_cmd "time $workingdir/indskflt_ct --tc=$testname --loggerPath=$cvt_logs_dir --pair[ -type=d-f -sd=$source_dev -td=$target_dir/target_file.tgt -subtest=$subtestname -log=$cvt_log_file ] >> $cvt_op_file 2>&1" "ignorefail"
    killall inm_dmit
    pkill inm_dmit

    local grepop=$(cat $cvt_op_file | grep -i "DI Test Passed")
    if [[ -z "${grepop// }" ]]; then
            echo "CVT test failed"
            mv $cvt_log_file $cvt_log_file.`date`
            mv $cvt_op_file $cvt_op_file.`date`
            return 1
    else
            echo "CVT test passed"
            return 0
    fi

}

run_tests()
{
    local failed=0
    local stime=10

    umount /data
    local diskname=`fdisk -l 2>/dev/null | grep -o /dev/sd[d-i]`
    log "Formatting Disk"
    yes | mkfs $diskname
    log "Mounting $diskname to /data"
    mkdir /data > /dev/null 2>&1
    mount $diskname /data

    rm -rf /data/*

    local testcases=('mixed' '16k_random' '16k_seq' '1mb_random' '1mb_seq' '4k_random' '4k_seq' '4mb_random' '4mb_seq' '512k_random' '512k_seq' '64k_random' '64k_seq' '8mb_random' '8mb_seq' '9mb_random' '9mb_seq')
    local ntests=${#testcases[@]}
    log "Total Tests: $ntests"

    local ctests=0

    cd $tdir > /dev/null 2>&1
    for testcase in "${testcases[@]}"; do
        echo -e "$ctests/$ntests\r"
        log "Starting $testcase test"
        startcvt "/dev/sdc" "/data" "$testcase" "$TESTNAME" > $tdir/$testcase.log 2>&1
        failed=$?
        if [[ $failed != 0 ]]; then
            sleep $stime
            # might have failed to take barrier, retry
            startcvt "/dev/sdc" "/data" "$testcase" "$TESTNAME" > $tdir/$testcase.log 2>&1
            failed=$?
        fi
        ((ctests++))

        if [ $failed -eq 1 ]; then
            log_dmesg
            failed_logs="$tdir/$testcase.log /tmp/dmesg.log"
            exit_with_logs $FAILED_TEST "$failed_logs"
            break
        fi

        sleep $stime
    done
    cd - > /dev/null 2>&1

    return $failed
}
set_test_params
run_tests
exit_with_logs $?
