#!/bin/bash

# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
# Description:
#     Download and run xfs tests.
#    - Supported Distros: Debian, Ubuntu, RHEL, Fedora, CentOS
#    - Supported disks: sdc, nvme0n1
#    - Supported filesystem tests: generic, btrfs, ext4, xfs
#######################################################################
XFSTestConfigFile="xfstests-config.config"
xfs_folder="xfstests"
dbench_folder="dbench"
xfs_git_url="git://git.kernel.org/pub/scm/fs/xfs/xfstests-dev.git"
dbench_git_url="https://github.com/sahlberg/dbench.git"
excluded_tests="generic/430 generic/431 generic/434 /xfs/438 xfs/490 btrfs/007 btrfs/178"

. utils.sh || {
    echo "ERROR: unable to source utils.sh!"
    echo "TestAborted" > state.txt
    exit 0
}
UtilsInit

ConfigureXFSTestTools() {
    GetDistro
    case "$DISTRO" in
        ubuntu*|debian*)
            until dpkg --force-all --configure -a; sleep 10; do echo 'Trying again...'; done
            pack_list="libacl1-dev libaio-dev libattr1-dev libgdbm-dev libtool-bin libuuid1 libuuidm-ocaml-dev sqlite3 uuid-dev uuid-runtime xfslibs-dev zlib1g-dev"
        ;;

        redhat*|centos*|fedora*)
            pack_list="btrfs-progs-devel libacl-devel libaio-devel libattr-devel libuuid-devel llvm-ocaml-devel sqlite uuid-devel xfsdump xfsprogs-devel xfsprogs-qa-devel zlib-devel"
        ;;

        suse*|sles*)
            pack_list="btrfsprogs libacl-devel libaio-devel libattr-devel libuuid-devel sqlite xfsdump xfsprogs-devel zlib-devel"
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
    install_package "acl attr automake bc dos2unix dump e2fsprogs gawk gcc git indent libtool lvm2 make nvme-cli parted python quota sed xfsdump xfsprogs"
    install_package $pack_list
    LogMsg "Packages installation complete."
    # Install dbench
    git clone $dbench_git_url $dbench_folder
    pushd $dbench_folder
    ./autogen.sh
    ./configure
    make -j $(nproc)
    make install
    popd
    # Install xfstests
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

Main() {
    if [ -e ${XFSTestConfigFile} ]; then
        LogMsg "${XFSTestConfigFile} file is present."
    else
        LogErr "missing ${XFSTestConfigFile} file"
        exit 0
    fi
    # Configure XFS Tools
    ConfigureXFSTestTools

    # Configure disks
    if [ -n "${NVME}" ]; then
        ConfigureDisks "nvme0n1" "nvme0n1p1" "nvme0n1p2" "$FSTYP" "test" "scratch"
    else
        ConfigureDisks "sdc" "sdc1" "sdc2" "$FSTYP" "test" "scratch"
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
    LogMsg "Starting xfstests run with cmd 'check -g ${FSTYP}/quick -E exclude.txt'"
    pushd $xfs_folder
    # Construct a list of excluded tests
    for test in ${excluded_tests}
    do
        echo $test >> exclude.txt
    done
    # Run xfstests
    bash check -g "$FSTYP"/quick -E exclude.txt >> xfstests.log
    popd
    cat ${xfs_folder}/xfstests.log >> TestExecution.log
    cat ${xfs_folder}/xfstests.log | tail -2 | grep tests
    if [ $? -ne 0 ]; then
        LogErr "xfstests run did not finish"
        SetTestStateFailed
        exit 0
    fi
    UpdateSummary "xfstests run finished successfully!"
    SetTestStateCompleted
    exit 0
}

Main