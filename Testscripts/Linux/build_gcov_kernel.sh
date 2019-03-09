#!/bin/bash

RESULTS="$(readlink -f ./results.txt)"

function report_result {
    echo "$1" > $RESULTS
}

function report_error {
    exit_code="$1"
    
    if [ $exit_code -ne 0 ];then
        report_result "$2"
        exit 0
    fi
}

. constants.sh || {
    report_result "NO_CONSTANTS"
}

set -x

function install_ubuntu_deps {
    apt -y update
    DEBIAN_FRONTEND=noninteractive apt install -y build-essential flex bison kernel-package libncurses-dev libelf-dev libssl-dev bzip2 git
    report_error $? "INSTALL_DEPS_ERROR"
}

function get_sources_from_git {
    git_url="$1"
    source_dest="$(readlink -f $2)"
    
    if [[ -d "$source_dest" ]];then
        rm -rf $source_dest
    fi
    
    git clone $git_url $source_dest
    report_error $? "GIT_CLONE_ERROR"
}

function get_sources_from_package {
    package_path="$(readlink -f $1)"
    source_dest="$(readlink -f $2)"

    work_dir=$(readlink -f ./temp)

    if [[ -d "$source_dest" ]];then
            rm -rf $source_dest
    fi
    mkdir -p "$source_dest"

    if [[ -d "$work_dir" ]];then
            rm -rf $work_dir
    fi
    mkdir -p $work_dir

    pushd $work_dir
    dpkg -x $package_path .
    report_error $? "DEB_EXTRACT_ERROR"
    
    archive_path=$(find . -name "linux-source*.bz2" | head -n 1)
    if [[ ! -e $archive_path ]];then
        report_error 1 "WRONG_PACKAGE_ERROR"
    fi

    mkdir sources
    bzip2 -dc $archive_path | tar xvf - -C ./sources
    mv ./sources/linux-source*/* $source_dest
    popd
}

function config_kernel {
    build_dir="$1"
    config_url="$2"
    
    pushd "$build_dir"
    make mrproper
    if [[ $config_url != "" ]];then
        wget $config_url -O new-config
        cp new-config .config
    fi
    make olddefconfig
    
    new_lines="CONFIG_CONSTRUCTORS=y\nCONFIG_GCOV_KERNEL=y\nCONFIG_GCOV_PROFILE_ALL=y\nCONFIG_GCOV_FORMAT_4_7=y\n# CONFIG_GCOV_PROFILE_FTRACE is not set"
    sed -i "s/# CONFIG_GCOV_KERNEL is not set/$new_lines/" .config
    popd
}

function build_kernel {
    build_dir="$1"

    pushd "$build_dir"
    make-kpkg --initrd -j"$(($(nproc) * 5))" kernel_image kernel_headers kernel_source
    report_error $? "KERNEL_BUILD_ERROR"
    popd
}

function collect_sources {
    KSRC=$1
    KOBJ=$2
    DEST=$3

    if [ -z "$KSRC" ] || [ -z "$KOBJ" ] || [ -z "$DEST" ]; then
        echo "Usage: $0 <ksrc directory> <kobj directory> <output.tar.gz>" >&2
        exit 1
    fi

    KSRC=$(cd $KSRC; printf "all:\n\t@echo \${CURDIR}\n" | make -f -)
    KOBJ=$(cd $KOBJ; printf "all:\n\t@echo \${CURDIR}\n" | make -f -)

    find $KSRC $KOBJ \( -name '*.gcno' -o -name '*.[ch]' -o -type l \) -a \
                     -perm /u+r,g+r | tar cfz $DEST -P -T -

    report_error $? "SOURCE_COLLECT_ERROR"
}

function archive_artifacts {
    build_dir="$1"
    packages_dest="$2"
    source_dest="$3"
    
    parent_dir=$(dirname $build_dir)
    
    pushd "$parent_dir"
    if [[ ! $(find *.deb) ]];then
        echo "Cannot find kernel packages"
        exit 0
    fi
    tar cvf packages.tar *.deb
    cp packages.tar $packages_dest
    popd
    
    collect_sources "$build_dir" "$build_dir" "$source_dest"
}

function main {
    while true;do
        case "$1" in
            --build_dir)
                BUILD_DIR=$2
                shift 2;;
            --source_dest)
                SOURCE_DEST=$(readlink -f $2)
                shift 2;;
            --packages_dest)
                PACKAGE_DEST=$(readlink -f $2)
                shift 2;;
            --git_repo)
                GIT_REPO=$2
                shift 2;;
            --package_path)
                PACKAGE_NAME="$2"
                shift 2;;
            --custom_config_url)
                CONFIG_URL=$2
                shift 2;;
            --) shift; break ;;
            *) break ;;
        esac
    done
    
    PACKAGE_PATH="$(PACKAGE_NAME=${PACKAGE_NAME##*\\}; echo ${PACKAGE_NAME##*/})"

    if [[ "$BUILD_DIR" == "" ]];then
        exit 0
    fi
    if [[ -d "$BUILD_DIR" ]];then
            rm -rf $BUILD_DIR
    fi
    mkdir -p $BUILD_DIR
    
    install_ubuntu_deps

    if [[ $PACKAGE_PATH != "" ]];then
        get_sources_from_package $PACKAGE_PATH $BUILD_DIR
    elif [[ $GIT_REPO != "" ]];then
        get_sources_from_git $GIT_REPO $BUILD_DIR
    fi

    config_kernel $BUILD_DIR $CONFIG_URL
    build_kernel $BUILD_DIR
    
    archive_artifacts $BUILD_DIR $PACKAGE_DEST $SOURCE_DEST
    
    if [[ ! -e $PACKAGE_DEST ]] || [[ ! -e $SOURCE_DEST ]];then
       report_error 1 "ARTIFACTS_MISSING_ERROR"
    else
       report_result "BUILD_SUCCEDED"
    fi
    
    exit 0
}

main --build_dir $BUILD_DIR --source_dest $SOURCE_DEST \
     --packages_dest $PACKAGE_DEST --package_path $SRC_PACKAGE_NAME \
     --custom_config_url $CONFIG_URL
