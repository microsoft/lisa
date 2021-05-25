#!/usr/bin/env bash
#######################################################################
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
# validate-intel-sgx-driver.sh
# Description:
#    Check the existence of Intel sgx driver.
#    Install Open-Enclave and build&run Samples
# Supported Distros:
#    Ubuntu
#######################################################################

set -e
set -x

sudo rm -rf state.txt
. utils.sh || {
    echo "Error: unable to source utils.sh!"
    echo "TestAborted" > state.txt
    exit 1
}

UtilsInit
SetTestStateRunning

rm -rf ~/samples

sudo DEBIAN_FRONTEND=noninteractive apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get upgrade -y -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold"
echo "----- Checking sgx driver -----"
if ! modinfo intel_sgx; then
    echo "modinfo intel_sgx failed"
    SetTestStateFailed
    exit 1
fi

function install_prereq_1804() {
    echo 'deb [arch=amd64] https://download.01.org/intel-sgx/sgx_repo/ubuntu bionic main' | sudo tee /etc/apt/sources.list.d/intel-sgx.list
    wget -qO - https://download.01.org/intel-sgx/sgx_repo/ubuntu/intel-sgx-deb.key | sudo apt-key add -

    echo "deb http://apt.llvm.org/bionic/ llvm-toolchain-bionic-7 main" | sudo tee /etc/apt/sources.list.d/llvm-toolchain-bionic-7.list
    wget -qO - https://apt.llvm.org/llvm-snapshot.gpg.key | sudo apt-key add -

    echo "deb [arch=amd64] https://packages.microsoft.com/ubuntu/18.04/prod bionic main" | sudo tee /etc/apt/sources.list.d/msprod.list
    wget -qO - https://packages.microsoft.com/keys/microsoft.asc | sudo apt-key add -
    sudo apt-get update

    echo "----- Install Open Enclave packages and dependencies -----"
    install_package "clang-7 libssl-dev gdb libsgx-enclave-common libsgx-enclave-common-dev libprotobuf10 libsgx-dcap-ql libsgx-dcap-ql-dev az-dcap-client open-enclave"
}

function install_prereq_1604() {
    echo 'deb [arch=amd64] https://download.01.org/intel-sgx/sgx_repo/ubuntu xenial main' | sudo tee /etc/apt/sources.list.d/intel-sgx.list
    wget -qO - https://download.01.org/intel-sgx/sgx_repo/ubuntu/intel-sgx-deb.key | sudo apt-key add -

    echo "deb http://apt.llvm.org/xenial/ llvm-toolchain-xenial-7 main" | sudo tee /etc/apt/sources.list.d/llvm-toolchain-xenial-7.list
    wget -qO - https://apt.llvm.org/llvm-snapshot.gpg.key | sudo apt-key add -

    echo "deb [arch=amd64] https://packages.microsoft.com/ubuntu/16.04/prod xenial main" | sudo tee /etc/apt/sources.list.d/msprod.list
    wget -qO - https://packages.microsoft.com/keys/microsoft.asc | sudo apt-key add -
    sudo apt-get update

    echo "----- Install Open Enclave packages and dependencies -----"
    install_package "clang-8 libssl-dev gdb libsgx-enclave-common libsgx-enclave-common-dev libprotobuf9v5 libsgx-dcap-ql libsgx-dcap-ql-dev az-dcap-client open-enclave"
}

install_azure_dcap_client() {
    #Follows guide at https://github.com/intel/SGXDataCenterAttestationPrimitives.git
    #======================================
    echo "Clone, build, install Azure DCAP Client"
    #======================================
    pushd .
    cd ~
    
    git clone https://github.com/microsoft/Azure-DCAP-Client.git
 
    # Adding permissions to be able to switch branches
    sudo chown -R $(whoami):$(whoami) ~/Azure-DCAP-Client/
 
    cd ~/Azure-DCAP-Client/
 
    sudo apt-get update -y
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

. /etc/lsb-release
echo "Script running on $DISTRIB_DESCRIPTION"

if [ "$DISTRIB_RELEASE" = "18.04" ]; then
    install_prereq_1804
elif [ "$DISTRIB_RELEASE" = "16.04" ]; then
    install_prereq_1604
else
    echo "$DISTRIB_RELEASE is unsupported"
    exit 1
fi

export AZDCAP_COLLATERAL_VERSION=v3
export AZDCAP_DEBUG_LOG_LEVEL=INFO
install_azure_dcap_client

echo "----- Running Samples Tests -----"
cd ~
cp -r /opt/openenclave/share/openenclave/samples/ ~
source /opt/openenclave/share/openenclave/openenclaverc
SAMPLES=$(find ~/samples/* -maxdepth 0 -type d)
NUM_PASS=0
for DIR in $SAMPLES; do
    pushd "$DIR"
    make build
    make run && let ++NUM_PASS
    popd
done
if [ $NUM_PASS -ne "$(wc -w <<< $SAMPLES)" ]; then
    SetTestStateFailed
    exit 1
fi

echo "----- Running FS/GS Enabled Test -----"
cd ~
cat <<EOF >main.c
#include <stdio.h>
#include <stdlib.h>
#include <signal.h>
#include <unistd.h>

#define handle_error(msg) \
    do { perror(msg); exit(-1); } while (0)

static void handler(int sig, siginfo_t *si, void *unused)
{
    exit(-1);
}

int main() {
    struct sigaction sa;
    sa.sa_flags = SA_SIGINFO;
    sigemptyset(&sa.sa_mask);
    sa.sa_sigaction = handler;
    if (sigaction(SIGILL, &sa, NULL) == -1)
        handle_error("sigaction");

    volatile unsigned long x;
    __asm__ volatile ( "rdfsbase %0" : "=r" (x) );
    __asm__ volatile ( "wrfsbase %0" :: "r" (x) );
    __asm__ volatile ( "rdgsbase %0" : "=r" (x) );
    __asm__ volatile ( "wrgsbase %0" :: "r" (x) );
    printf("SUCCESS\n");
    exit(0);
}
EOF
gcc -o test-fsgs-enabled ./main.c
if [[ "$(./test-fsgs-enabled)" != "SUCCESS" ]]; then
    SetTestStateFailed
    exit 1
fi

SetTestStateCompleted
exit 0
