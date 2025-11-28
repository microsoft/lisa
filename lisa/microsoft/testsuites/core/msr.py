# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import semver
from assertpy import assert_that

from lisa import (
    RemoteNode,
    SkippedException,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.operating_system import (
    CBLMariner,
    CpuArchitecture,
    Debian,
    Fedora,
    Linux,
    Redhat,
    Suse,
)
from lisa.sut_orchestrator import AZURE, HYPERV
from lisa.tools import Lscpu, Modprobe
from lisa.util import MissingPackagesException

# See docs for hypercall spec, sharing os info
# is required before making hypercalls.
#  https://learn.microsoft.com/en-us/virtualization/hyper-v-on-windows/tlfs/hypercall-interface#guest-os-identity-for-proprietary-operating-systems

# build info: bits 0-15
BUILD_INFO_MASK = 0x0000_0000_0000_FFFF
# service pack, bits 16-23
SERVICE_PACK_MASK = 0x0000_0000_00FF_0000
# minor version, bits 24-31
MINOR_VERSION_MASK = 0x0000_0000_FF00_0000
# major version, bits 32-39
MAJOR_VERSION_MASK = 0x0000_00FF_0000_0000
# OS ID  bits 40-47
OS_ID_MASK = 0x0000_FF00_0000_0000
# vendor ID: bits 48-62
VENDOR_ID_MASK = 0x7FFF_0000_0000_0000
# the all important 'is open source os' flag.
# indicates whether is *nix or other non-winodws
# os.  the final bit, bit 63
IS_OPEN_SOURCE_OS_MASK = 0x8000_0000_0000_0000


class HvOsPlatformInfo:
    # HV_REGISTER_GUEST_OSID constant declared in linus kernel source:
    # arch/{ARCH_NAME}/include/asm/hyperv-tlfs.h
    HV_REGISTER_GUEST_OSID = {
        CpuArchitecture.ARM64: "0x00090002",
        CpuArchitecture.X64: "0x40000000",
    }
    OS_ID_UNDEFINED = 0
    OS_ID_MSDOS = 1
    OS_ID_WINDOWS_3 = 2
    OS_ID_WINDOWS_9 = 3
    OS_ID_WINDOWS_NT = 4
    OS_ID_WINDOWS_CE = 5
    OS_ID_ALL = {
        OS_ID_UNDEFINED: "UNDEFINED",
        OS_ID_MSDOS: "MSDOS",
        OS_ID_WINDOWS_3: "WINDOWS_3",
        OS_ID_WINDOWS_9: "WINDOWS_9",
        OS_ID_WINDOWS_NT: "WINDOWS_NT",
        OS_ID_WINDOWS_CE: "WINDOWS_CE",
    }

    def __init__(self, msr_register_content: int) -> None:
        self.os_vendor_id = (msr_register_content & VENDOR_ID_MASK) >> 48
        self.os_id = (msr_register_content & OS_ID_MASK) >> 40
        self.kernel_major = (msr_register_content & MAJOR_VERSION_MASK) >> 32
        self.kernel_minor = (msr_register_content & MINOR_VERSION_MASK) >> 24
        self.kernel_patch = (msr_register_content & SERVICE_PACK_MASK) >> 16
        self.kernel_build = msr_register_content & BUILD_INFO_MASK
        self.is_open_source_os = bool(msr_register_content & IS_OPEN_SOURCE_OS_MASK)

    def get_os_id(self) -> str:
        try:
            return self.OS_ID_ALL[self.os_id]
        except KeyError:
            return f"UNKNOWN OS (0x{hex(self.os_id)})"

    def get_kernel_version(self) -> semver.VersionInfo:
        return semver.VersionInfo(
            self.kernel_major,
            self.kernel_minor,
            self.kernel_patch,
            build=str(self.kernel_build),
        )

    def __str__(self) -> str:
        return (
            f"OSID: {self.get_os_id()} "
            f"VendorID: {hex(self.os_vendor_id)} "
            f"Kernel: {str(self.get_kernel_version())} "
            f"IsOpenSource?:{self.is_open_source_os}"
        )


@TestSuiteMetadata(
    area="msr",
    category="functional",
    description="""
    Test suite verifies hyper-v platform id is set correctly via hypercall to host.
    Theoretically, this could work for any guest which uses hypercalls
    on Hyper-V or Azure.
    """,
    requirement=simple_requirement(
        supported_os=[Linux], supported_platform_type=[AZURE, HYPERV]
    ),
)
class Msr(TestSuite):
    @TestCaseMetadata(
        description="""
            verify platform id is accurate in msr register
        """,
        priority=1,
    )
    def verify_hyperv_platform_id(self, node: RemoteNode) -> None:
        distro = node.os
        if isinstance(distro, Redhat):
            # Install EPEL only for RHEL/CentOS, not Fedora
            # Fedora already has comprehensive package repositories
            distro.install_epel()
        elif isinstance(distro, (Debian, Suse, CBLMariner, Fedora)):
            # no special setup, same package name
            pass
        else:
            raise SkippedException("MSR platform id test not yet supported on this OS.")

        # get the msr offset to read, this constant is arch specific
        arch_id = node.tools[Lscpu].get_architecture()
        try:
            arch_msr_offset = HvOsPlatformInfo.HV_REGISTER_GUEST_OSID[arch_id]
        except KeyError as missing_key:
            raise SkippedException(f"Arch {missing_key} is not supported by msr test")

        # try installing msr-tools if rdmsr isn't already insalled.
        if node.execute("command -v rdmsr", shell=True, sudo=True).exit_code != 0:
            try:
                distro.install_packages("msr-tools")
            except AssertionError:
                raise SkippedException(
                    "Could not install msr-tools and rdmsr was not available."
                )
            except MissingPackagesException:
                raise SkippedException("Cannot find package msr-tools or rdmsr binary")

        # bail if rdmsr wasn't in msr-tools packacge.
        if node.execute("command -v rdmsr", shell=True, sudo=True).exit_code != 0:
            raise SkippedException("rdmsr isn't available after install of msr-tools.")

        # load the msr module, skip with status if it's broken on this system.
        try:
            node.tools[Modprobe].load("msr")
        except AssertionError:
            raise SkippedException(
                "Could not load msr module, package may be broken for this OS."
            )

        # read the content of the msr register
        id_information = node.execute(
            f"rdmsr {arch_msr_offset}",
            shell=True,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "Could not run rdmsr to fetch platform id info from msr"
            ),
        ).stdout

        # Documentation link is near the mask definitons above.
        node.log.info(f"MSR register contained OS information: {id_information}")

        # register content is a packed 64 bit unsigned integer.
        msr_register_content = int(id_information, 16)

        # parse the bitfield...
        hv_os_platform_info = HvOsPlatformInfo(msr_register_content)

        # pretty print
        node.log.info(f"Found OS Info: {str(hv_os_platform_info)}")

        # verify is_open_source flag is set, this is required for reporting
        # os health info in azure.
        assert_that(hv_os_platform_info.is_open_source_os).described_as(
            "OS_TYPE not set to OPEN_SOURCE in hv platform info bitfield. "
            f"Expected {hex(msr_register_content)} & "
            f"{hex(IS_OPEN_SOURCE_OS_MASK)} != 0. "
            "This indicates this bitfield was declared incorrectly. See: "
            "https://git.launchpad.net/~canonical-kernel/ubuntu/+source/linux-azure/"
            "+git/jammy/tree/include/asm-generic/hyperv-tlfs.h?h=master#n129 "
            "for one example of how to declate the correct values. "
            "To verify this bug: pull the source for this distro+release and check "
            "include/asm-generic/hyperv-tlfs.h for the definition of "
            "HV_LINUX_VENDOR_ID."
        ).is_not_zero()


# NOTE: further work: checking the kernel version matches checking for known
#       manufacturer ids, etc.
#       implementing this platform ID info is not required for use with hyper-v
#       but is for hv guest extensions and azure platform health reporting.
