#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

function install_packages {
    apt -y update
    apt install -y python-pip zip
    pip install gcovr
}

function main {
    while true;do
        case "$1" in
            --build_dir)
                BUILD_DIR=$2
                shift 2;;
            --test_category)
                TEST_CATEGORY=$2
                shift 2;;
            --gcov_path)
                GCOV_PATH=$2
                shift 2;;
            --) shift; break ;;
            *) break ;;
        esac
    done
    
    WORK_DIR=$(readlink -f .)
    
    install_packages
    
    if [[ ! -e "${BUILD_DIR}" ]];then
        echo "Cannot find sources directory"
        exit 0
    fi
    
    if [[ ! -e "${GCOV_PATH}" ]];then
        echo "Cannot find sources directory"
        exit 0
    fi
    
    pushd $BUILD_DIR
    rm *.gcov
    mv $GCOV_PATH .
    gcovr -g -k --html --html-details -o ./${TEST_CATEGORY}.html -v --exclude-directories debian
    zip "${TEST_CATEGORY}.zip" *.html
    cp "${TEST_CATEGORY}.zip" $WORK_DIR
    popd
}

main $@