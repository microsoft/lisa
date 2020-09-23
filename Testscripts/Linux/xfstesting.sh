#!/bin/bash

# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
# Description:
#     Download and run xfs tests.
#    - Supported Distros: Debian, Ubuntu, RHEL, Fedora, CentOS
#    - Supported disks: sdc, nvme0n1
#    - Supported filesystem tests: generic, btrfs, ext4, xfs
#
# Details on excluded tests:
#  - generic/211 - test takes too long to run on high RAM capacity VM.
#
#######################################################################
XFSTestConfigFile="xfstests-config.config"
xfs_folder="xfstests"
dbench_folder="dbench"
xfs_git_url="git://git.kernel.org/pub/scm/fs/xfs/xfstests-dev.git"
dbench_git_url="https://github.com/sahlberg/dbench.git"
excluded_tests="generic/211 generic/430 generic/431 generic/434 /xfs/438 xfs/490 btrfs/007 btrfs/178"
excluded_cifs="generic/013 generic/014 generic/070 generic/117 generic/430 generic/431 generic/434 generic/438 generic/476"
. utils.sh || {
    echo "ERROR: unable to source utils.sh!"
    echo "TestAborted" > state.txt
    exit 0
}
UtilsInit

ConfigureXFSTestTools() {
    case "$DISTRO" in
        ubuntu*|debian*)
            until dpkg --force-all --configure -a; sleep 10; do echo 'Trying again...'; done
            pack_list=(libacl1-dev libaio-dev libattr1-dev libgdbm-dev libtool-bin libuuid1 libuuidm-ocaml-dev sqlite3 uuid-dev uuid-runtime xfslibs-dev zlib1g-dev)
            check_package "btrfs-tools"
            if [ $? -eq 0 ]; then
                pack_list+=(btrfs-tools)
            fi
            check_package "btrfs-progs"
            if [ $? -eq 0 ]; then
                pack_list+=(btrfs-progs)
            fi
        ;;

        redhat*|centos*|fedora*)
            pack_list=(libacl-devel libaio-devel libattr-devel libuuid-devel sqlite xfsdump xfsprogs-devel xfsprogs-qa-devel zlib-devel btrfs-progs-devel llvm-ocaml-devel uuid-devel)
            which python || [ -f /usr/libexec/platform-python ] && ln -s /usr/libexec/platform-python /sbin/python
        ;;

        suse*|sles*)
            pack_list=(btrfsprogs libacl-devel libaio-devel libattr-devel libuuid-devel sqlite xfsdump xfsprogs-devel zlib-devel)
        ;;
        *)
            LogErr "OS Version not supported in InstallDependencies!"
            SetTestStateFailed
            exit 0
        ;;
    esac
    # Install common & specific dependencies
    update_repos
    install_fio
    pack_list+=(acl attr automake bc cifs-utils dos2unix dump e2fsprogs gawk gcc git libtool lvm2 make parted quota sed xfsdump xfsprogs indent python)
    for package in "${pack_list[@]}"; do
        check_package "$package"
        if [ $? -eq 0 ]; then
            install_package "$package"
        fi
    done
    if [ -n "${NVME}" ]; then
        install_nvme_cli
    fi
    modprobe btrfs
    LogMsg "Packages installation complete."
    # Install dbench
    LogMsg "Remove folder $dbench_folder if exists."
    rm -rf $dbench_folder
    git clone $dbench_git_url $dbench_folder
    pushd $dbench_folder
    ./autogen.sh
    ./configure
    make -j $(nproc)
    make install
    popd
    # Install xfstests
    LogMsg "Remove folder $xfs_folder if exists."
    rm -rf $xfs_folder
    git clone $xfs_git_url $xfs_folder
    pushd $xfs_folder
    ./configure
    make -j $(nproc)
    make install
    if [ 0 -ne $? ]; then
        LogErr "Failed to install xfstests. Check if 'make' runs successfully"
        SetTestStateFailed
        exit 0
    fi
    popd
    LogMsg "Successfully installed xfstests"

    # Create required users
    useradd fsgqa
    groupadd fsgqa
    useradd 123456-fsgqa
}

ConfigureDisks() {
    disk_location=$1
    main_partition=$2
    secondary_partition=$3
    filesystem=$4
    main_mountpoint=$5
    secondary_mountpoint=$6

    # Delete previous partitions
    sync
    umount -l "/dev/${main_partition}"
    umount -l "/dev/${secondary_partition}"
    parted -s -- "/dev/${disk_location}" mklabel gpt
    sleep 1 ; sync
    # Partition disk
    parted -s -- "/dev/${disk_location}" mkpart primary 1 50%
    sleep 1 ; sync
    parted -s -- "/dev/${disk_location}" mkpart secondary 50% 100%
    sleep 1 ; sync
    # Create filesystem
    if [ ${filesystem} == "ext4" ]; then
        extra_opts=""
    else
        extra_opts="-f"
    fi
    echo "y" | mkfs.${filesystem} ${extra_opts} "/dev/${main_partition}"
    sleep 5
    echo "y" | mkfs.${filesystem} ${extra_opts} "/dev/${secondary_partition}"
    sleep 5
    # Create test folders
    mkdir $main_mountpoint ; mkdir $secondary_mountpoint
    # Put remaining params in the config file
    echo "SCRATCH_DEV=/dev/${secondary_partition}" >> ${XFSTestConfigFile}
    echo "SCRATCH_MNT=/root/${secondary_mountpoint}" >> ${XFSTestConfigFile}
}

ConfigureCIFS() {
    main_mountpoint=$1
    secondary_mountpoint=$2
    mkdir $main_mountpoint
    mkdir $secondary_mountpoint

    for test in ${excluded_cifs}
    do
        echo $test >> exclude_cifs.txt
    done
    cp exclude_cifs.txt $xfs_folder

    # Create credentials
    if [ -d "/etc/smbcredentials" ]; then
       rm -rf /etc/smbcredentials
    fi
    mkdir /etc/smbcredentials

    if [ ! -f "/etc/smbcredentials/lisav2.cred" ]; then
        echo "username=${share_user}" >> /etc/smbcredentials/lisav2.cred
        echo "password=${share_pass}" >> /etc/smbcredentials/lisav2.cred
    fi
    chmod 600 /etc/smbcredentials/lisav2.cred
    cp -f /etc/fstab /etc/fstab_cifs
    echo "//${share_main} ${main_mountpoint} ${FSTYP} ${fstab_info}" >> /etc/fstab
    echo "//${share_scratch} ${secondary_mountpoint} ${FSTYP} ${fstab_info}" >> /etc/fstab
    echo "SCRATCH_MNT=${secondary_mountpoint}" >> ${XFSTestConfigFile}
}

Main() {
    # Get VM kernel version. Recommend to 3.12 or later for SMB3.0 in Azure.
    # However, we passed this test in CentOS/RHEL 7.6 or later.
    if [[ $DISTRO_NAME == "centos" || $DISTRO_NAME == "rhel" ]]; then
        dj=$(echo $DISTRO_VERSION | cut -d "." -f 1)
        dn=$(echo $DISTRO_VERSION | cut -d "." -f 2)
        if [ $dj -le 7 ] && [ $dn -lt 6 ]; then
            LogErr "Recommended distro version is RHEL/CentOS 7.6 or later"
            SetTestStateSkipped
            exit 0
        fi
    else
        mj=$(uname -r | cut -d '-'  -f1 | cut -d '.' -f 1)
        mn=$(uname -r | cut -d '-'  -f1 | cut -d '.' -f 2)
        if [ $mj -lt 4 ] && [ $mn -lt 12 ]; then
            LogErr "Recommended kernel version of SMB3.0 is 3.12 or later version"
            SetTestStateSkipped
            exit 0
        fi
    fi

    if [ -e ${XFSTestConfigFile} ]; then
        LogMsg "${XFSTestConfigFile} file is present."
    else
        LogErr "missing ${XFSTestConfigFile} file"
        exit 0
    fi
    GetDistro
    config_path=$(get_bootconfig_path)

    grep -q "CONFIG_BTRFS_FS is not set" $config_path
    if [ $? -eq 0 ] && [ $FSTYP == "btrfs" ];then
        LogMsg "CONFIG_BTRFS_FS is not set in $config_path file in ${DISTRO}, skip the test"
        SetTestStateSkipped
        exit 0
    fi

    grep -q "CONFIG_CIFS is not set" $config_path
    if [ $? -eq 0 ] && [ $FSTYP == "cifs" ];then
        LogMsg "CONFIG_CIFS is not set in $config_path file in ${DISTRO}, skip the test"
        SetTestStateSkipped
        exit 0
    fi

    #Refer https://access.redhat.com/documentation/en-us/red_hat_enterprise_linux/8/html/considerations_in_adopting_rhel_8/file-systems-and-storage_considerations-in-adopting-rhel-8
    if [ $DISTRO == "redhat_8" ] && [ $FSTYP == "btrfs" ]; then
        LogMsg "${DISTRO} doesn't support $FSTYP filesystem."
        SetTestStateSkipped
        exit 0
    fi
    if [ $DISTRO == "coreos" ]; then
        LogMsg "Distro not supported. Skip the test."
        SetTestStateSkipped
        exit 0
    fi
    # Configure XFS Tools
    ConfigureXFSTestTools

    # Configure disks
    if [ -n "${NVME}" ]; then
        ConfigureDisks "nvme0n1" "nvme0n1p1" "nvme0n1p2" "$FSTYP" "test" "scratch"
    else
        if [ $FSTYP == "cifs" ]; then
            ConfigureCIFS "/root/test" "/root/scratch"
        else
            # Check which disk is attached to the VM as custom storage.
            # Azure provides links in /dev/disk/azure/ to /dev/sd[a-z] devices
            # this is needed as some 5+ kernels do not assign drive letters in any particular order
            # (previously the test disk was /dev/sdc)
            testDisk=$(readlink -f /dev/disk/azure/scsi1/* | sed "s@/dev/@@g" | head -1)
            ConfigureDisks "${testDisk}" "${testDisk}1" "${testDisk}2" "$FSTYP" "test" "scratch"
            # Configure disk in env and xfstests config file
            TEST_DEV="/dev/${testDisk}1"
            echo "TEST_DEV=${TEST_DEV}" >> ${XFSTestConfigFile}
        fi
    fi
    # Copy config file into the xfstests folder
    dos2unix ${XFSTestConfigFile}
    cp -f ${XFSTestConfigFile} ${xfs_folder}/local.config

    #
    # Start testing
    #
    # Check if generic tests must be run
    if [ -n "${GENERIC}" ]; then
        FSTYP="generic"
    fi
    pushd $xfs_folder
    # Construct a list of excluded tests
    for test in ${excluded_tests}
    do
        echo $test >> exclude.txt
    done
    # Run xfstests
    if [ $FSTYP == "cifs" ]; then
        LogMsg "Starting xfstests run with cmd 'check -g generic/quick -E exclude_cifs.txt'"
        bash check -g generic/quick -E exclude_cifs.txt >> xfstests.log
    else
        LogMsg "Starting xfstests run with cmd 'check -g ${FSTYP}/quick -E exclude.txt'"
        bash check -g "$FSTYP"/quick -E exclude.txt >> xfstests.log
    fi
    popd
    cat ${xfs_folder}/xfstests.log >> TestExecution.log
    cat ${xfs_folder}/xfstests.log | tail -2 | grep tests
    if [ $? -ne 0 ]; then
        LogErr "xfstests run did not finish"
        SetTestStateFailed
        exit 0
    fi
    UpdateSummary "xfstests run finished successfully!"
    [ -f /etc/fstab_cifs ] && cp -f /etc/fstab_cifs /etc/fstab
    SetTestStateCompleted
    exit 0
}

Main
