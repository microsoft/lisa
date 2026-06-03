#!/bin/bash -x
#
# CVT test script that runs without VM extensions.
# Downloads binaries from provided URLs, loads driver if needed, and runs CVT.
#
# Usage: cvt_no_extension.sh <test_dir> <cvt_binaries_url> [driver_tarball_url]
#
# Arguments:
#   test_dir           - Working directory for test files
#   cvt_binaries_url   - URL to download CVT binaries archive (indskflt_ct + inm_dmit)
#   driver_tarball_url - URL to download driver tarball (optional, skipped if driver loaded)

set -o pipefail

test_dir=$1
cvt_binaries_url=$2
driver_tarball_url=$3

FAILED_TEST=1
PASSED_TEST=0

cvt_log_file="$test_dir/cvt.log"
cvt_status_file="$test_dir/cvt_status.json"
dmesg_log_file="$test_dir/dmesg.log"

log()
{
    echo "$(date):[cvt] -> $*" | tee -a "$cvt_log_file"
}

log_dmesg()
{
    dmesg -c > "$dmesg_log_file" 2>/dev/null || true
}

# --- cvt_status.json management ---
# Mirrors the JSON structure from the private CVT pipeline:
# { testStatus, startTime, lastUpdated, testDetails: { vmName, os, kernelVersion,
#   driverVersion, productVersion, testCases: [{name, status, time}] } }

init_cvt_status()
{
    local vm_name=$(hostname)
    local os_name=""
    if [ -f /etc/os-release ]; then
        os_name=$(. /etc/os-release && echo "$NAME $VERSION")
    fi
    local kernel_ver=$(uname -r)
    local start_time=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

    cat > "$cvt_status_file" <<EOF
{
    "testStatus": "Running",
    "startTime": "$start_time",
    "lastUpdated": "$start_time",
    "testDetails": {
        "vmName": "$vm_name",
        "os": "$os_name",
        "kernelVersion": "$kernel_ver",
        "driverVersion": "",
        "productVersion": "",
        "testCases": [
        ]
    }
}
EOF
    log "Initialized cvt_status.json"
}

update_cvt_status_field()
{
    # Update a top-level or testDetails field using sed (no python dependency)
    local key="$1"
    local value="$2"
    local timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

    if [ ! -f "$cvt_status_file" ]; then
        return
    fi

    # Update lastUpdated
    sed -i "s|\"lastUpdated\":.*|\"lastUpdated\": \"$timestamp\",|" "$cvt_status_file"

    case "$key" in
        testStatus)
            sed -i "s|\"testStatus\":.*|\"testStatus\": \"$value\",|" "$cvt_status_file"
            ;;
        driverVersion|productVersion)
            sed -i "s|\"$key\":.*|\"$key\": \"$value\",|" "$cvt_status_file"
            ;;
    esac
}

update_cvt_status_testcase()
{
    # Add or update a test case entry in the JSON
    local tc_name="$1"
    local tc_status="$2"
    local tc_time="$3"
    local timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

    if [ ! -f "$cvt_status_file" ]; then
        return
    fi

    sed -i "s|\"lastUpdated\":.*|\"lastUpdated\": \"$timestamp\",|" "$cvt_status_file"

    # Check if test case already exists (update in place) or add new
    if grep -q "\"name\": \"$tc_name\"" "$cvt_status_file"; then
        # Use awk for multi-line update of existing test case
        awk -v name="$tc_name" -v status="$tc_status" -v time="$tc_time" '
        /"name":/ && index($0, "\"" name "\"") {
            print; getline;
            sub(/"status": "[^"]*"/, "\"status\": \"" status "\"");
            print; getline;
            sub(/"time": "[^"]*"/, "\"time\": \"" time "\"");
            print; next
        }
        {print}
        ' "$cvt_status_file" > "${cvt_status_file}.tmp" && mv "${cvt_status_file}.tmp" "$cvt_status_file"
    else
        # Count existing entries to determine if we need a comma before insertion
        local existing_count=$(grep -c '"name":' "$cvt_status_file")
        local comma=""
        if [ "$existing_count" -gt 0 ]; then
            comma=","
        fi
        # Insert new test case before the closing ] of testCases array
        awk -v entry="            {\"name\": \"$tc_name\", \"status\": \"$tc_status\", \"time\": \"$tc_time\"}" \
            -v comma="$comma" '
        /^[[:space:]]*\]/ && found_cases {
            if (comma != "") print comma entry; else print entry;
            found_cases=0
        }
        /"testCases"/ { found_cases=1 }
        {print}
        ' "$cvt_status_file" > "${cvt_status_file}.tmp" && mv "${cvt_status_file}.tmp" "$cvt_status_file"
    fi
}

exit_with_retcode()
{
    log_dmesg
    local ret=$1
    if [ $ret -eq 0 ]; then
        log "CVT Test succeeded"
        update_cvt_status_field "testStatus" "Succeeded"
    else
        log "CVT Test failed"
        update_cvt_status_field "testStatus" "Failed"
    fi
    echo "TEST_STATUS:$ret"
    exit "$ret"
}

download_file()
{
    local url="$1"
    local output="$2"

    log "Downloading $url to $output"
    local wget_opts="-O"
    if [ "${SKIP_TLS_VERIFY:-0}" = "1" ]; then
        log "WARNING: TLS certificate verification disabled via SKIP_TLS_VERIFY"
        wget_opts="--no-check-certificate -O"
    fi
    wget $wget_opts "$output" "$url" 2>&1 | tee -a "$cvt_log_file"
    if [ $? -ne 0 ]; then
        log "Failed to download from $url"
        return 1
    fi
    return 0
}

is_driver_loaded()
{
    # Check both lsmod and /proc/modules for robustness
    if lsmod 2>/dev/null | grep -q "involflt"; then
        return 0
    fi
    if grep -q "involflt" /proc/modules 2>/dev/null; then
        return 0
    fi
    return 1
}

ensure_device_node()
{
    # Ensure /dev/involflt is a char device with the correct major number
    local maj_num=$(cat /proc/devices | grep involflt | awk '{print $1}')
    if [ -z "$maj_num" ]; then
        log "Cannot find involflt in /proc/devices"
        return 1
    fi

    if [ -c /dev/involflt ]; then
        log "Filter device /dev/involflt already exists (major=$maj_num)"
        return 0
    fi

    rm -f /dev/involflt 2>/dev/null
    mknod /dev/involflt c $maj_num 0
    chmod 666 /dev/involflt
    log "Filter device /dev/involflt created (major=$maj_num)"
    return 0
}

load_driver()
{
    if is_driver_loaded; then
        log "Filter driver is already loaded, skipping driver installation"
        ensure_device_node
        return $?
    fi

    if [ -z "$driver_tarball_url" ]; then
        log "Driver is not loaded and no driver_tarball_url provided"
        return 1
    fi

    log "Driver not loaded, downloading and installing..."
    local driver_tarball="$test_dir/drivers.tar.gz"
    download_file "$driver_tarball_url" "$driver_tarball" || return 1

    tar -xzf "$driver_tarball" -C "$test_dir" 2>&1 | tee -a "$cvt_log_file"
    if [ $? -ne 0 ]; then
        log "Failed to extract driver tarball"
        return 1
    fi

    # Find the involflt.ko matching current kernel
    local ker_ver=$(uname -r)
    local k_dir="/lib/modules/$ker_ver/kernel/drivers/char"
    mkdir -p "$k_dir"

    local drivers_dir="$test_dir/Drivers"
    if [ ! -d "$drivers_dir" ]; then
        # Try finding extracted driver directory
        drivers_dir=$(find "$test_dir" -type d -name "Drivers" 2>/dev/null | head -1)
    fi

    if [ -z "$drivers_dir" ] || [ ! -d "$drivers_dir" ]; then
        log "Cannot find Drivers directory after extraction"
        return 1
    fi

    log "Looking for driver matching kernel $ker_ver in $drivers_dir"

    # Try exact match first
    local driver_file=""
    if [ -f "$drivers_dir/involflt.ko.${ker_ver}" ]; then
        driver_file="$drivers_dir/involflt.ko.${ker_ver}"
    elif [ -f "$drivers_dir/UnSigned/involflt.ko.${ker_ver}" ]; then
        driver_file="$drivers_dir/UnSigned/involflt.ko.${ker_ver}"
    else
        # Fallback: find any involflt.ko file
        driver_file=$(find "$drivers_dir" -name "involflt.ko*" 2>/dev/null | head -1)
    fi

    if [ -z "$driver_file" ]; then
        log "Cannot find involflt.ko for kernel $ker_ver"
        return 1
    fi

    log "Using driver: $driver_file"
    cp -f "$driver_file" "$k_dir/involflt.ko" || return 1

    modinfo "$k_dir/involflt.ko" 2>&1 | tee -a "$cvt_log_file"
    insmod "$k_dir/involflt.ko" 2>&1 | tee -a "$cvt_log_file"

    if ! is_driver_loaded; then
        log "Failed to load filter driver"
        return 1
    fi

    log "Filter driver loaded successfully"
    ensure_device_node
    return $?
}

download_cvt_binaries()
{
    local archive="$test_dir/cvt_binaries.tar.gz"
    download_file "$cvt_binaries_url" "$archive" || return 1

    tar -xzf "$archive" -C "$test_dir" 2>&1 | tee -a "$cvt_log_file"
    if [ $? -ne 0 ]; then
        log "Failed to extract CVT binaries archive"
        return 1
    fi

    # Verify binaries exist
    if [ ! -f "$test_dir/indskflt_ct" ] || [ ! -f "$test_dir/inm_dmit" ]; then
        # Try finding them in subdirectories
        local found_ct=$(find "$test_dir" -name "indskflt_ct" -type f 2>/dev/null | head -1)
        local found_dmit=$(find "$test_dir" -name "inm_dmit" -type f 2>/dev/null | head -1)
        if [ -n "$found_ct" ]; then
            cp -f "$found_ct" "$test_dir/indskflt_ct"
        fi
        if [ -n "$found_dmit" ]; then
            cp -f "$found_dmit" "$test_dir/inm_dmit"
        fi
    fi

    if [ ! -f "$test_dir/indskflt_ct" ]; then
        log "indskflt_ct binary not found after extraction"
        return 1
    fi
    if [ ! -f "$test_dir/inm_dmit" ]; then
        log "inm_dmit binary not found after extraction"
        return 1
    fi

    chmod +x "$test_dir/indskflt_ct"
    chmod +x "$test_dir/inm_dmit"
    log "CVT binaries ready: indskflt_ct, inm_dmit"
    return 0
}

identify_source_and_target_disk()
{
    log "Identifying data disks by size..."
    local all_disks=$(fdisk -l 2>/dev/null | grep "^Disk /dev/" | grep -v "loop\|ram" | awk '{print $2}' | sed 's/://')

    for disk in $all_disks; do
        local disk_size=$(blockdev --getsize64 "$disk" 2>/dev/null)
        if [ "$disk_size" = "1073741824" ]; then
            src_disk=$disk
            log "Source disk (1 GB): $src_disk"
        elif [ "$disk_size" = "10737418240" ]; then
            tgt_disk=$disk
            log "Target disk (10 GB): $tgt_disk"
        fi
    done

    if [ -z "$src_disk" ]; then
        log "Error: Could not find source (1 GB) disk"
        return 1
    fi
    if [ -z "$tgt_disk" ]; then
        log "Error: Could not find target (10 GB) disk"
        return 1
    fi
    return 0
}

get_testname()
{
    TESTNAME="barrierhonourwithouttag"
    local curr_kernel=$(uname -r)
    local major_ver=$(echo "$curr_kernel" | cut -f1 -d'.')
    local minor_ver=$(echo "$curr_kernel" | cut -f2 -d'.')

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
    log "Setting test params"
    local timeout=60000
    get_testname
    if [ "$TESTNAME" = "barrierhonourwithouttag" ]; then
        timeout=600000
    fi

    "$test_dir/inm_dmit" --set_attr VacpIObarrierTimeout $timeout 2>&1 | tee -a "$cvt_log_file" || {
        log "Failed to set VacpIObarrierTimeout"
        return 1
    }

    "$test_dir/inm_dmit" --set_attr DirtyBlockHighWaterMarkServiceRunning 30000 2>&1 | tee -a "$cvt_log_file" || {
        log "Failed to set DirtyBlockHighWaterMarkServiceRunning"
        return 1
    }

    return 0
}

startcvt()
{
    local source_dev=$1
    local target_dir=$2
    local subtestname=$3
    local testname=$4
    local cvt_logs_dir="$test_dir/cvt_logs"
    local cvt_log="$cvt_logs_dir/cvtlog_$subtestname.txt"
    local cvt_op="$cvt_logs_dir/cvt_$subtestname.txt"

    if ! is_driver_loaded; then
        log "Driver not loaded, cannot run test"
        return 1
    fi

    mkdir -p "$cvt_logs_dir"

    "$test_dir/inm_dmit" --op=start_notify &
    local dmit_pid=$!

    time "$test_dir/indskflt_ct" \
        --tc="$testname" \
        --loggerPath="$cvt_logs_dir" \
        --pair[ -type=d-f -sd="$source_dev" -td="$target_dir/target_file.tgt" \
        -subtest="$subtestname" -log="$cvt_log" ] >> "$cvt_op" 2>&1

    kill $dmit_pid 2>/dev/null
    wait $dmit_pid 2>/dev/null

    if grep -qi "DI Test Passed" "$cvt_op"; then
        log "$subtestname: PASSED"
        return $PASSED_TEST
    else
        log "$subtestname: FAILED"
        return $FAILED_TEST
    fi
}

run_tests()
{
    local failed=0
    local stime=10
    local ctests=0
    local mnt_path="/data"

    umount "$mnt_path" 2>/dev/null || true
    log "Formatting target disk $tgt_disk"
    yes | mkfs "$tgt_disk" 2>&1 | tee -a "$cvt_log_file"
    if [ ${PIPESTATUS[1]} -ne 0 ]; then
        log "ERROR: mkfs failed on $tgt_disk"
        blkid "$tgt_disk" 2>&1 | tee -a "$cvt_log_file"
        exit_with_retcode "$FAILED_TEST"
    fi
    mkdir -p "$mnt_path"
    mount "$tgt_disk" "$mnt_path"
    if [ $? -ne 0 ]; then
        log "ERROR: mount failed for $tgt_disk on $mnt_path"
        blkid "$tgt_disk" 2>&1 | tee -a "$cvt_log_file"
        mount 2>&1 | tee -a "$cvt_log_file"
        exit_with_retcode "$FAILED_TEST"
    fi

    local testcases=('mixed' '16k_random' '16k_seq' '1mb_random' '1mb_seq' '4k_random' '4k_seq' '4mb_random' '4mb_seq' '512k_random' '512k_seq' '64k_random' '64k_seq' '8mb_random' '8mb_seq' '9mb_random' '9mb_seq')
    local ntests=${#testcases[@]}
    log "Total Tests: $ntests"

    # Initialize all test cases in status file
    for testcase in "${testcases[@]}"; do
        update_cvt_status_testcase "$testcase" "NotStarted" "0"
    done

    cd "$test_dir" || exit_with_retcode "$FAILED_TEST"
    for testcase in "${testcases[@]}"; do
        log "[$ctests/$ntests] Starting $testcase test"
        update_cvt_status_testcase "$testcase" "Running" "0"
        local test_start_time=$(date +%s)

        startcvt "$src_disk" "$mnt_path" "$testcase" "$TESTNAME" > "$test_dir/$testcase.log" 2>&1
        failed=$?
        if [ $failed -ne 0 ]; then
            sleep $stime
            # Retry once — barrier acquisition can be transient
            startcvt "$src_disk" "$mnt_path" "$testcase" "$TESTNAME" > "$test_dir/$testcase.log" 2>&1
            failed=$?
        fi
        ((ctests++))

        local test_end_time=$(date +%s)
        local execution_time=$((test_end_time - test_start_time))

        if [ $failed -ne 0 ]; then
            log "$testcase test FAILED after retry"
            update_cvt_status_testcase "$testcase" "Failed" "$execution_time"
            exit_with_retcode "$FAILED_TEST"
        fi

        update_cvt_status_testcase "$testcase" "Succeeded" "$execution_time"
        log "$testcase test succeeded (${execution_time}s)"
        sleep $stime
    done

    return $failed
}

# --- Main ---
log "=== CVT No-Extension Test Start ==="
log "Test dir: $test_dir"
log "CVT binaries URL: $cvt_binaries_url"
log "Driver tarball URL: ${driver_tarball_url:-not provided}"
log "Kernel: $(uname -r)"

mkdir -p "$test_dir"
init_cvt_status

# Ensure DNS is working (Azure VMs sometimes lose resolv.conf on reboot)
if ! nslookup aka.ms >/dev/null 2>&1; then
    log "DNS not working, current resolv.conf:"
    cat /etc/resolv.conf 2>/dev/null | tee -a "$cvt_log_file"
    if ! grep -q "168.63.129.16" /etc/resolv.conf 2>/dev/null; then
        echo "nameserver 168.63.129.16" >> /etc/resolv.conf
        log "Added Azure DNS nameserver 168.63.129.16"
    else
        log "Azure DNS already in resolv.conf but resolution still failing"
    fi
fi

load_driver || exit_with_retcode $?
download_cvt_binaries || exit_with_retcode $?

# Update driver/product version in status after driver is loaded and inm_dmit is available
local_driver_ver=$("$test_dir/inm_dmit" --op=get_driver_version 2>/dev/null | grep "Driver" | cut -d" " -f4- | tr -d ' ')
local_product_ver=$("$test_dir/inm_dmit" --op=get_driver_version 2>/dev/null | grep "Product" | cut -d" " -f4- | tr -d ' ')
update_cvt_status_field "driverVersion" "${local_driver_ver:-unknown}"
update_cvt_status_field "productVersion" "${local_product_ver:-unknown}"

identify_source_and_target_disk || exit_with_retcode $?
set_test_params || exit_with_retcode $?
run_tests
exit_with_retcode $?
