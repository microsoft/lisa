#!/bin/bash

RED='\e[31m'
GRE='\e[32m'
NC='\e[0m' # No Color

LOG_DIR_PATH=~/log-files

# TODO: Fix issue with Cirrus .. to remove these checks. Work Item: 6337631
ROOT_DIR_PATH=$( cd "$(dirname "${BASH_SOURCE[0]}")" ; pwd -P )
TESTS_DIR_PATH=$ROOT_DIR_PATH/tests/
ACC_TEST_NAME=$1

if [[ -d "../tests/" ]]
then
    echo "Running form Source Code..."
    TESTS_DIR_PATH=../tests/
fi

if [[ -d "/usr/sbin/azperf/" ]]
then
    echo "Running form Package..."
    sudo apt install -y jq
    ACC_TEST_NAME=$(cat '/usr/sbin/azperf/RunModel.json' | jq -r '.TestParameters.ACCTestName')
    echo "Running Tests: $ACC_TEST_NAME"
fi

# Initialize DCAP specific environment variables early
DCAP_BASE_CERT_URL=$(python3 $TESTS_DIR_PATH/get_env.py DCAP_BASE_CERT_URL)
if [[ ! -z $DCAP_BASE_CERT_URL ]]; then
    echo "Found DCAP_BASE_CERT_URL, setting environment variable AZDCAP_BASE_CERT_URL=$DCAP_BASE_CERT_URL"
    export AZDCAP_BASE_CERT_URL=$DCAP_BASE_CERT_URL
else
    echo "Could not find DCAP_BASE_CERT_URL to set environment variable AZDCAP_BASE_CERT_URL"
fi 

DCAP_COLLATERAL_VERSION=$(python3 $TESTS_DIR_PATH/get_env.py DCAP_COLLATERAL_VERSION)
if [[ ! -z $DCAP_COLLATERAL_VERSION ]]; then
    echo "Found DCAP_COLLATERAL_VERSION, setting environment variable AZDCAP_COLLATERAL_VERSION=$DCAP_COLLATERAL_VERSION"
    export AZDCAP_COLLATERAL_VERSION=$DCAP_COLLATERAL_VERSION 
else
    echo "Could not find DCAP_COLLATERAL_VERSION to set environment variable AZDCAP_COLLATERAL_VERSION"
fi
    
DCAP_DEBUG_LOG_LEVEL=$(python3 $TESTS_DIR_PATH/get_env.py DCAP_DEBUG_LOG_LEVEL)
if [[ ! -z $DCAP_DEBUG_LOG_LEVEL ]]; then
    echo "Found DCAP_DEBUG_LOG_LEVEL, setting environment variable AZDCAP_DEBUG_LOG_LEVEL=$DCAP_DEBUG_LOG_LEVEL"
    export AZDCAP_DEBUG_LOG_LEVEL=$DCAP_DEBUG_LOG_LEVEL
else
    echo "Could not find DCAP_DEBUG_LOG_LEVEL to set environment variable AZDCAP_DEBUG_LOG_LEVEL"
fi


install_prereqs(){
    sudo apt-get -y update
    sudo DEBIAN_FRONTEND=noninteractive apt-get --yes --force-yes -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold" upgrade
    sudo DEBIAN_FRONTEND=noninteractive apt-get --yes --force-yes -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold" dist-upgrade
    sudo apt-get -y upgrade

    sudo -H apt-get -y install gcc python3 python3-dev python3-pip msr-tools
    sudo -H pip3 install -r $TESTS_DIR_PATH/requirements.txt
    sudo modprobe msr
}

clone_build_install_oesdk(){
    echo "----- Cloning OpenEnclave SDK ---------------"
    OESDK_COMMIT_ID=$(python3 $TESTS_DIR_PATH/get_env.py OESDK_COMMIT_ID)

    pushd .
    cd ~
    git clone https://github.com/openenclave/openenclave.git --depth 1
    cd openenclave
    git fetch --unshallow

    if [[ ! -z $OESDK_COMMIT_ID ]]; then
        COMMIT_NOT_FOUND_ERROR=$(git branch -a --contains $OESDK_COMMIT_ID 2>&1 >/dev/null)
        if [[  "$COMMIT_NOT_FOUND_ERROR" != *"error"* ]]; then
            echo "Commit $OESDK_COMMIT_ID is found from git history"
            git checkout $OESDK_COMMIT_ID
        else
            echo "Commit $OESDK_COMMIT_ID is not found from git history, stay on top of master"
        fi
    else
        OESDK_COMMIT_ID=$(git rev-parse HEAD)
        echo "Commit $OESDK_COMMIT_ID is found from git history"
    fi

    git submodule update --init --recursive

    # Install ansible
    n=0
    until [ "$n" -ge 5 ]
    do
        sudo scripts/ansible/install-ansible.sh && break
        n=$((n+1)) 
        sleep 15
    done

    # Run ACC Playbook
    n=0
    until [ "$n" -ge 5 ]
    do
        sudo ansible-playbook -vvvv scripts/ansible/oe-contributors-acc-setup.yml && break
        n=$((n+1)) 
        sleep 15
    done

    echo "----- Building OpenEnclave SDK -----------"
    mkdir build
    cd build
    cmake -G "Unix Makefiles" ..
    make
    echo "----- Installing OpenEnclave SDK Package ---------"
    cmake -G "Unix Makefiles" -DCMAKE_INSTALL_PREFIX=~/openenclave-install .. >$LOG_DIR_PATH/cmake_output.log 2>$LOG_DIR_PATH/cmake_err.log
    make install > null
    popd

}

uninstall_sgx_driver(){
   sudo /sbin/modprobe -r intel_sgx
   sudo dkms remove -m sgx -v $PACKAGE_VERSION --all
}

cleanup() {
    rm -rf ~/openenclave
    rm -rf ~/openenclave-install
    rm -rf ~/.az-dcap-client
    rm -rf $LOG_DIR_PATH
    uninstall_sgx_driver
}

install_sgx_driver(){
    #Follows guide at https://github.com/intel/SGXDataCenterAttestationPrimitives.git
    #======================================
    echo "Clone, build, install SGX driver"
    #======================================
    pushd . 
    cd ~
    dpkg-query -s linux-headers-$(uname -r)
    sudo apt-get install linux-headers-$(uname -r)
    sudo apt-get install libssl-dev
    git clone https://github.com/intel/SGXDataCenterAttestationPrimitives.git
    cd SGXDataCenterAttestationPrimitives/driver/linux
    make

    sudo apt-get -y install dkms
    . dkms.conf

    mkdir /usr/src/sgx-$PACKAGE_VERSION
    cp * -r /usr/src/sgx-$PACKAGE_VERSION

    sudo dkms add -m sgx -v $PACKAGE_VERSION
    sudo dkms build -m sgx -v $PACKAGE_VERSION
    sudo dkms install -m sgx -v $PACKAGE_VERSION
    sudo /sbin/modprobe intel_sgx
    popd
}

install_azure_dcap_client(){
    #Follows guide at https://github.com/intel/SGXDataCenterAttestationPrimitives.git
    #======================================
    echo "Clone, build, install Azure DCAP Client"
    #======================================
    pushd . 
    cd ~

    DCAP_COMMIT_ID=$(python3 $TESTS_DIR_PATH/get_env.py DCAP_COMMIT_ID)
    
    git clone https://github.com/microsoft/Azure-DCAP-Client.git

    # Adding permissions to be able to switch branches
    sudo chown -R $(whoami):$(whoami) ~/Azure-DCAP-Client/

    cd ~/Azure-DCAP-Client/

    # Temporarily using private icelake branch with prod fixes
    if [[ ! -z $DCAP_COMMIT_ID ]]; then
        COMMIT_NOT_FOUND_ERROR=$(git branch -a --contains $DCAP_COMMIT_ID 2>&1 >/dev/null)
        if [[  "$DCAP_COMMIT_ID" != *"error"* ]]; then
            echo "Commit $DCAP_COMMIT_ID is found from git history"
            git checkout $DCAP_COMMIT_ID
        else
            echo "Commit $DCAP_COMMIT_ID is not found from git history, stay on top of master"
        fi
    else
        DCAP_COMMIT_ID=$(git rev-parse HEAD)
        echo "Commit $DCAP_COMMIT_ID is found from git history"
    fi

    sudo apt-get update -y
    sudo apt-get install libssl-dev
    sudo apt install libcurl4-openssl-dev
    sudo apt-get install pkg-config
    sudo add-apt-repository ppa:team-xbmc/ppa -y
    sudo apt-get update -y
    sudo apt-get install nlohmann-json3-dev
    sudo apt-get install -y libgtest-dev
    sudo apt-get install -y cmake
    cd /usr/src/gtest
    sudo cmake CMakeLists.txt
    sudo make

    # Copy or symlink libgtest.a and libgtest_main.a to /usr/lib folder.
    sudo cp *.a /usr/lib

    # Building library.
    cd ~/Azure-DCAP-Client/src/Linux/
    sudo ./configure
    sudo make
    sudo make install

    # Ensure correct DCAP quote provider is picked up
    if [ -f /usr/lib/libdcap_quoteprov.so ] && [ -f /usr/local/lib/libdcap_quoteprov.so ];
    then
        echo "Moving /usr/lib/libdcap_quoteprov.so to /usr/lib/temp_libdcap_quoteprov.so"
        sudo mv /usr/lib/libdcap_quoteprov.so /usr/lib/temp_libdcap_quoteprov.so
        echo "Moving /usr/local/lib/libdcap_quoteprov.so to /usr/lib/libdcap_quoteprov.so"
        sudo cp /usr/local/lib/libdcap_quoteprov.so /usr/lib/libdcap_quoteprov.so
    else
        echo "Could not find /usr/lib/libdcap_quoteprov.so and /usr/local/lib/libdcap_quoteprov.so"
    fi

    echo "Printing information about /usr/lib/libdcap_quoteprov.so"
    ls -l /usr/lib/libdcap_quoteprov.so

    echo "Printing environment variables after DCAP setup"
    printenv
    echo "Done printing environment variables after DCAP setup"

    popd
}

check_sgx_files(){
    echo "Checking if all necessary SGX files and packages exist..."

    intel_sgx_packages=("libsgx-enclave-common" "libsgx-ae-qve" "libsgx-ae-pce" "libsgx-ae-qe3" "libsgx-qe3-logic" "libsgx-pce-logic")
    for package in "${intel_sgx_packages[@]}"
    do
    apt search "${package}"
    done

    intel_dcap_packages=("libsgx-dcap-ql" "libsgx-dcap-ql-dev" "libsgx-urts" "libsgx-quote-ex" "sgx-aesm-service" "libsgx-aesm-ecdsa-plugin" "libsgx-aesm-pce-plugin" "libsgx-aesm-quote-ex-plugin" "az-dcap-client")
    for package in "${intel_dcap_packages[@]}"
    do
    apt search "${package}"
    done

    packages_validation_distribution_directories="/usr/lib"
    packages_validation_distribution_files=("libsgx_enclave_common.so.1" "libsgx_pce_logic.so" "libsgx_qe3_logic.so" "libsgx_dcap_ql.so" "libdcap_quoteprov.so")
    for file in "${packages_validation_distribution_files[@]}"
    do
    find "${packages_validation_distribution_directories}" -iname "${file}"
    done

    echo "Checking if all necessary SGX files and packages exist... Done"
}

run_tests(){
    echo "-------- Running Tests --------"
    echo
    pushd .
    cd $TESTS_DIR_PATH
    pytest general_tests -v -s $ACC_TEST_NAME 2>&1 | tee -a $LOG_DIR_PATH/tests-output.log
    popd
}

upload_log_files(){
    echo "Uploading Logs..."
    pushd .
    cd $TESTS_DIR_PATH
    python3 $TESTS_DIR_PATH/reporter/upload_log.py
    echo "Done"
    echo
    popd
}

run_acc_tests(){
    cleanup

    mkdir $LOG_DIR_PATH

    install_prereqs 2>&1 | tee -a $LOG_DIR_PATH/process-install.log
    if [ $? -ne 0  ]; then
        echo -e "${RED}install_prereqs failed${NC}"
    fi

    clone_build_install_oesdk 2>&1 | tee -a $LOG_DIR_PATH/process-install.log
    if [ $? -ne 0  ]; then
        echo -e "${RED}clone_build_install_oesdk failed${NC}"
    fi

    install_sgx_driver 2>&1 | tee -a $LOG_DIR_PATH/process-install.log
    if [ $? -ne 0  ]; then
        echo -e "${RED}install_sgx_driver failed${NC}"
    fi

    install_azure_dcap_client 2>&1 | tee -a $LOG_DIR_PATH/process-install.log
    if [ $? -ne 0  ]; then
        echo -e "${RED}install_azure_dcap_client failed${NC}"
    fi

    check_sgx_files 2>&1 | tee -a $LOG_DIR_PATH/process-install.log
    if [ $? -ne 0  ]; then
        echo -e "${RED}check_sgx_files failed${NC}"
    fi

    sudo cat /var/log/kern.log > $LOG_DIR_PATH/kernel-output.log

    # Dump environment variables as a sanity check
    echo "----- Environment Variable Dump -------------"
    printenv | tee $LOG_DIR_PATH/env.log
    echo "----- End Environment Variable Dump ---------"

    run_tests
    upload_log_files
}


if [[ "${#BASH_SOURCE[@]}" -eq 1 ]]; then
    run_acc_tests "$@"
fi