from assertpy import assert_that

from lisa import (
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.features import acc
from lisa.operating_system import Debian
from lisa.tools import Dmesg, Make, Wget, Whoami
from lisa.util import SkippedException, UnsupportedDistroException


@TestSuiteMetadata(
    area="ACC_BVT",
    category="functional",
    description="""
    This Basic Validation Test (BVT) suite validates the availability of Secure Guard
    Extensions (SGX) on a given
    platform.
    """,
)
class ACCBasicTest(TestSuite):
    @TestCaseMetadata(
        description="""

        This case verifies if the VM is SGX Enabled.

        Steps:
            1. Add keys and tool chain from Intel-SGX, LLVM and Microsoft repositories.
            2. Install DCAP driver if missing.
            3. Install required package.
            4. Run Helloworld and Remote Attestation tests.

        """,
        priority=1,
        requirement=simple_requirement(
            supported_features=[acc.ACC],
        ),
    )
    def verify_sgx(self, log: Logger, node: Node) -> None:

        if isinstance(node.os, Debian) & (node.os.information.version == "18.4.0"):
            os_version = "18.04"
        elif isinstance(node.os, Debian) & (node.os.information.version == "20.4.0"):
            os_version = "20.04"
        else:
            raise SkippedException(
                UnsupportedDistroException(
                    node.os, f"os version: {node.os} is not supported"
                )
            )

        assert isinstance(node.os, Debian), f"unsupported distro {node.os}"

        # INSTALL 3 PREREQUISITES
        # 1.  Get Intel SGX Repo for Ubuntu
        #
        # <  echo 'deb [arch=amd64] https://download.01.org/intel-
        #    sgx/sgx_repo/ubuntu bionic main' |
        #   sudo tee /etc/apt/sources.list.d/intel-sgx.list >
        # <  wget -qO - https://download.01.org/intel-sgx/sgx_repo/
        #   ubuntu/intel-sgx-deb.key |
        #   sudo apt-key add - >
        node.os.add_repository(
            repo=(
                "deb [arch=amd64] https://download.01.org/"
                f"intel-sgx/sgx_repo/ubuntu {node.os.information.codename} main"
            ),
            keys_location=[
                "https://download.01.org/intel-sgx/sgx_repo/ubuntu"
                "/intel-sgx-deb.key",
            ],
        )

        # 2.  Get LLVM toolchain
        #
        # <  echo "deb http://apt.llvm.org/bionic/ llvm-toolchain-bionic-7 main" |
        #   sudo tee /etc/apt/sources.list.d/llvm-toolchain-bionic-7.list >
        # < wget -qO - https://apt.llvm.org/llvm-snapshot.gpg.key |
        #   sudo apt-key add - >

        toolchain = f"llvm-toolchain-{node.os.information.codename}"
        node.os.add_repository(
            repo=(
                "deb http://apt.llvm.org/"
                f"{node.os.information.codename}/ "
                f"{toolchain} main"
            ),
            keys_location=["https://apt.llvm.org/llvm-snapshot.gpg.key"],
        )

        # 3. Get Ubuntu 20.04 packages from Microsoft prod repo
        #
        # < echo "deb [arch=amd64] https://packages.microsoft.com/ubuntu/18.04/
        #   prod bionic main" |
        #   sudo tee /etc/apt/sources.list.d/msprod.list >
        # < wget -qO - https://packages.microsoft.com/keys/microsoft.asc
        #   | sudo apt-key add - >

        node.os.add_repository(
            repo=(
                "deb [arch=amd64] https://packages.microsoft.com/"
                f"ubuntu/{os_version}/prod {node.os.information.codename} main"
            ),
            keys_location=[
                "https://packages.microsoft.com/keys/microsoft.asc",
            ],
        )

        # Verify if Intel DCAP client installed.
        #
        # <get dmesg dmesg | grep -i sgx>

        dmesg = node.tools[Dmesg]
        if "sgx" not in dmesg.get_output():
            node.os.install_packages("dkms")
            wget = node.tools[Wget]
            driver_path = wget.get(
                url="https://download.01.org/intel-sgx/sgx-dcap/1.7/"
                f"linux/distro/ubuntu{os_version}-server/sgx_linux_x64_driver_1.35.bin",
                filename="sgx_linux_x64_driver.bin",
                executable=True,
            )
            node.execute(driver_path, sudo=True)

        # Install other packages
        # < sudo apt -y install clang-10 libssl-dev gdb libsgx-enclave-common
        #   libsgx-quote-ex libprotobuf10 libsgx-dcap-ql libsgx-dcap-ql-dev
        #   az-dcap-client open-enclave >

        if os_version == "18.04":
            libprotobuf = "libprotobuf10"
        else:
            libprotobuf = "libprotobuf17"

        node.os.install_packages(
            f"clang-10 libssl-dev gdb libsgx-enclave-common libsgx-quote-ex "
            f"{libprotobuf} libsgx-dcap-ql libsgx-dcap-ql-dev "
            "az-dcap-client open-enclave"
        )

        # Copy Samples from the Binary
        #
        # <cp -r /opt/openenclave/share/openenclave/samples ~/mysamples>

        samples_folder = node.get_working_path() / "mysamples"
        copy_cmd = "cp -r /opt/openenclave/share/openenclave/samples " + str(
            samples_folder
        )
        node.execute(copy_cmd, shell=True)

        # Run Hello World and Remote Attestation
        helloworld_dir = samples_folder / "helloworld"
        attestation_dir = samples_folder / "attestation"
        source_command = ". /opt/openenclave/share/openenclave/openenclaverc"
        fail_msg = "HELLO WORLD TEST FAILED"

        node.tools[Make]
        result = node.execute(
            f"{source_command} && make build && make run",
            cwd=helloworld_dir,
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=fail_msg,
        )

        assert_that(result.stdout).described_as("error message").contains(
            "Enclave called into host to print: Hello World!"
        )

        fail_msg = "REMOTE ATTESTATION HAS FAILED"
        username = node.tools[Whoami].get_username()
        node.execute(f"usermod -a -G sgx_prv {username}", shell=True, sudo=True)
        node.execute("export SGX_AESM_ADDR=1", shell=True, sudo=True)
        result = node.execute(
            f"{source_command} && make build && make run ",
            cwd=attestation_dir,
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=fail_msg,
            sudo=True,
        )
        assert_that(
            "Decrypted data matches with the enclave internal secret data"
            in result.stdout
        ).described_as("some message").is_true()
