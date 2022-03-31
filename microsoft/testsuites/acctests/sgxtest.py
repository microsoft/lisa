# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import os
import pytest
import subprocess

from typing import Any
from pathlib import Path
from typing import Any
from assertpy import assert_that

from lisa import (
    CustomScript,
    CustomScriptBuilder,
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.operating_system import Posix
from lisa.tools import Echo, Uname

########### HELPER METHODS ###################

@staticmethod
def getOEInstalledPath():
    return os.path.expanduser("~/openenclave-install/")

@staticmethod
def getSGXVersion():
    if isOeInstalled():
        openenclave_install_path = getOEInstalledPath()
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!STARTED")
        print(openenclave_install_path)
        stdout = node.execute([openenclave_install_path + "bin/oesgx"], shell=True)
        oesgx = stdout
        sgx_version = ""
        if "CPU supports Software Guard Extensions:SGX1" in oesgx:
            sgx_version = "sgx1"
        elif "CPU supports Software Guard Extensions:SGX2" in oesgx:
            sgx_version = "sgx2"
            
    return sgx_version

@staticmethod
def isOeInstalled():
    if not os.path.expanduser('~/openenclave-install/bin/'):
        log.info("Not running test because openenclave binaries did not get installed.")
        return False
    return True


def runOESamples(SAMPLES):
    openenclave_install_path = getOEInstalledPath()
    samples_stdout = ""
    for sample in SAMPLES:
        if sys.platform == "linux":
            command = (
                ". {}/share/openenclave/openenclaverc; make build; make run".format(
                    openenclave_install_path
                ),
            )
        elif sys.platform == "win32":
            command = "vcvars64.bat & set OpenEnclave_DIR={}/lib/openenclave/cmake & cmake -G Ninja -DNUGET_PACKAGE_PATH=C:/oe_prereqs & ninja".format(
                openenclave_install_path
            )

        returncode, stdout = execute(
            command,
            shell=True,
            cwd="{}share/openenclave/samples/{}".format(
                openenclave_install_path, sample
            ),
            env=my_env,
        )
        samples_stdout += stdout
    return returncode

#############################################################

@TestSuiteMetadata(
    area="ACC",
    category="functional",
    owner="acc@microsoft.com",
    description="""
    This is a part of ACC test suite.
    This test case validates the installation of SGX. 
    The Suite consists of 2 sets of tests:
    1. High priority Level 0 test: verifyOE
    2. Lower Priority Level 1 test: runAllOESamples 

    verifyOE: Runs basic tests that validate SGX platform. 
    runAllOESamples: Runs all samples
    """,
    requirement=simple_requirement(unsupported_os=[]),
)
class SgxTestSuite(TestSuite):
    #This is a run_acc_tests.sh script initializer. 
    #run_acc_tests.sh installs and sets up OE 
    # On the node
    #To Do: Remove unnecessary tests
    def before_suite(self, log: Logger, **kwargs: Any) -> None:
        self._acctest_script = CustomScriptBuilder(
            Path(__file__).parent.joinpath("scripts"), ["run_acc_tests.sh"]
        )
    TIMEOUT = 2000
    @TestCaseMetadata(
        description="""
        This test case validates functionality of Secure Guard Extensions platform.
            1. Validate if OpenEnclave is installed on the Node
            2. Get SGX version
            3. Perform Remote Attestation and Hello world on the Node
        """,
        priority=0,
        timeout=TIMEOUT,
        use_new_environment=False,
    )
    def verifyOE(self, node: Node, log: Logger) -> None:
        #GET GUEST OS VERSION
        if node.os.is_posix:
            assert isinstance(node.os, Posix)
            info = node.tools[Uname].get_linux_information()
            log.info(
                f"release: '{info.uname_version}', "
                f"version: '{info.kernel_version_raw}', "
                f"hardware: '{info.hardware_platform}', "
                f"os: '{info.operating_system}'"
            )
        else:
            log.info("windows operating system")

        #CHECK IF OE IS INSTALLED
        script: CustomScript = node.tools[self._acctest_script]
        result1 = script.run()
        python = node.tools[Python]

        openenclave_install_path = python.run(
            f'-c "os.path.expanduser("~/openenclave-install/")"',
            force_run=True,
        )       
        
        if openenclave_install_path:
            #Run oesgx tool that comes with OESDK to get the version
            oesgx = node.execute([openenclave_install_path + "bin/oesgx"], shell=True)
            sgx_version = ""
            if "CPU supports Software Guard Extensions:SGX1" in oesgx:
                sgx_version = "sgx1"
            elif "CPU supports Software Guard Extensions:SGX2" in oesgx:
                sgx_version = "sgx2"
            log.info(sgx_version)
            assert sgx_version

            #RUN REMOTE ATTESTATION
            SAMPLES = [
            "helloworld",
            "attestation"
            ]
            returncode = runOESamples(SAMPLES)
            assert returncode == 0

            #CHECK PROCESS OUTPUT.
            echo = node.tools[Echo]
            assert_that(result.stdout).is_equal_to(0)
            assert_that(result.stderr).is_equal_to("")
            assert_that(result.exit_code).is_equal_to(0)
         else:
            log.info("Openenclave is currently not installed on the VM")
        
    @TestCaseMetadata(
        description="""
        This is a test case that runs all the ctests.
        """,
        priority=1,
    )

    def runAllOESamples(self, log: Logger, node: Node) -> None:
        log.info("Running all ACC OE Samples: ")
        tests_to_run = (
            "tests/attestation_cert_api"
            "|tests/attestation_plugin"
            "|tests/crypto"
            "|tests/crypto_crls_cert_chains"
            "|tests/debug-"
            "|tests/nodebug-"
            "|tests/echo"
            "|tests/file"
            "|tests/hostcalls"
            "|tests/host_verify"
            "|tests/memory"
            "|tests/ocall"
            "|tests/oeedger8r"
            "|tests/print"
            "|tests/qeidentity"
            "|tests/report"
            "|tests/sealKey"
            "|tests/tls_e2e"
            "|tests/oesign"
            "|tests/VectorException"
            "|tests/resolver"
            "|tests/datagram"
            "|tests/ids"
            "|tests/hostfs"
            "|tests/socketpair"
            "|tests/fs"
            "|tests/sockets"
            "|tests/poller"
            "|tests/sendmsg"
            "|tests/epoll"
        )

        command = ["ctest", "-V", "-R", tests_to_run]
        returncode, stdout = node.execute(
            command, cwd=os.path.expanduser("~/openenclave/build")
        )