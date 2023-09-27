import re
from typing import Pattern

from lisa import (
    LisaException,
    Node,
    SkippedException,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.operating_system import Linux, Posix
from lisa.sut_orchestrator import AZURE
from lisa.tools import Dmesg, KernelConfig, Lsmod, Modprobe


@TestSuiteMetadata(
    area="mana_driver",
    category="functional",
    description="""
    This test suite checks for the presence of mana and mana_ib drivers
    """,
)
class ManaDriverCheck(TestSuite):
    MANA_DRIVER_MESSAGE_PATTERN = re.compile(r"\[\s*[0-9.]+\s*\]\s+mana\s+.*")
    MANA_IB_DRIVER_MESSAGE_PATTERN = re.compile(r"\[\s*[0-9.]+\s*\]\s+mana_ib\s+.*")
    MANA_EN_KCONFIG = "CONFIG_MICROSOFT_MANA"
    MANA_IB_KCONFIG = "CONFIG_MANA_INFINIBAND"

    def _check_for_driver(
        self,
        node: Node,
        driver_name: str,
        kconfig_variable: str,
        dmesg_pattern: Pattern[str],
        verify_module_loads: bool = False,
    ) -> None:
        dmesg = node.tools[Dmesg]
        lsmod = node.tools[Lsmod]
        modprobe = node.tools[Modprobe]
        kconfig = node.tools[KernelConfig]

        # Check kconfig for mana
        mana_is_builtin = kconfig.is_built_in(kconfig_variable)
        mana_is_module = kconfig.is_built_as_module(kconfig_variable)
        if mana_is_builtin:
            node.log.info(f"{driver_name} is reported as builtin in kconfig")
        elif mana_is_module:
            node.log.info(
                f"{driver_name} is reported as a loadable kernel module in kconfig"
            )
        else:
            node.log.info(
                (
                    f"{driver_name} is not in kconfig for this image, "
                    "checking if driver is present (possible out of tree build)"
                )
            )

        # check modprobe for loadable module
        module_exists = modprobe.module_exists(driver_name)
        module_loaded = modprobe.is_module_loaded(driver_name)

        # if it isn't loaded, will not load, and isn't builtin, fail fast.
        if not any([module_loaded, module_exists, mana_is_builtin]):
            raise LisaException(f"{driver_name} is not present on this system")

        # allow return before loading check to enable kconfig only test
        if not verify_module_loads:
            return

        # If module is not loaded, but is loadable, attempt to load the module
        # This will throw if the module isn't found.
        if module_exists and not (mana_is_builtin or module_loaded):
            node.log.info(f"Attempting to load {driver_name} driver with modprobe...")
            modprobe.load(driver_name)
            # verify driver is loaded with lsmod
            module_loaded = lsmod.module_exists(driver_name, force_run=True)
            if not module_loaded:
                raise LisaException(
                    f"MANA driver {driver_name} was not detected after loading."
                )

        # finally, verify that mana driver logs are present after loading.
        kernel_driver_output = dmesg.get_output(force_run=True)
        matches = dmesg_pattern.search(kernel_driver_output)
        if not matches:
            raise LisaException(
                (
                    f"{driver_name} driver reported as present but "
                    f"no {driver_name} logs in driver messages."
                )
            )

    @TestCaseMetadata(
        description="""
        This test case checks for the mana ethernet driver.
        """,
        priority=3,
        requirement=simple_requirement(
            supported_platform_type=[AZURE], supported_os=[Posix]
        ),
    )
    def verify_mana_en_driver_present(self, node: Node) -> None:
        if not node.nics.is_mana_device_present():
            raise SkippedException(
                "MANA driver tests should be run in a MANA VM environment"
            )

        distro = node.os
        if isinstance(distro, Linux):
            if distro.get_kernel_information().version < "5.15.0":
                raise SkippedException("MANA is not available for kernels < 5.15")

        mana_driver_name = "mana"
        self._check_for_driver(
            node,
            driver_name=mana_driver_name,
            kconfig_variable=self.MANA_EN_KCONFIG,
            dmesg_pattern=self.MANA_DRIVER_MESSAGE_PATTERN,
            verify_module_loads=True,
        )

    @TestCaseMetadata(
        description="""
        This test case checks for the mana ethernet driver.
        """,
        priority=3,
        requirement=simple_requirement(
            supported_platform_type=[AZURE], supported_os=[Posix]
        ),
    )
    def verify_mana_ib_driver_present(self, node: Node) -> None:
        if not node.nics.is_mana_device_present():
            raise SkippedException(
                "MANA driver tests should be run in a MANA VM environment"
            )

        distro = node.os
        if isinstance(distro, Linux):
            if distro.get_kernel_information().version < "5.15.0":
                raise SkippedException("MANA is not available for kernels < 5.15")

        mana_driver_name = "mana_ib"
        # Check kconfig for mana
        self._check_for_driver(
            node,
            driver_name=mana_driver_name,
            kconfig_variable=self.MANA_IB_KCONFIG,
            dmesg_pattern=self.MANA_IB_DRIVER_MESSAGE_PATTERN,
            verify_module_loads=True,
        )

    @TestCaseMetadata(
        description="""
        This test case checks kconfig only for the mana ethernet driver.
        """,
        priority=3,
        requirement=simple_requirement(
            supported_platform_type=[AZURE], supported_os=[Posix]
        ),
    )
    def verify_mana_en_driver_kconfig(self, node: Node) -> None:
        distro = node.os
        if isinstance(distro, Linux):
            if distro.get_kernel_information().version < "5.15.0":
                raise SkippedException("MANA is not available for kernels < 5.15")

        mana_driver_name = "mana"
        self._check_for_driver(
            node,
            driver_name=mana_driver_name,
            kconfig_variable=self.MANA_EN_KCONFIG,
            dmesg_pattern=self.MANA_DRIVER_MESSAGE_PATTERN,
            verify_module_loads=False,
        )

    @TestCaseMetadata(
        description="""
        This test case checks kconfig only for the mana infiniband driver.
        """,
        priority=3,
        requirement=simple_requirement(
            supported_platform_type=[AZURE], supported_os=[Posix]
        ),
    )
    def verify_mana_ib_driver_kconfig(self, node: Node) -> None:
        distro = node.os
        if isinstance(distro, Linux):
            if distro.get_kernel_information().version < "5.15.0":
                raise SkippedException("MANA is not available for kernels < 5.15")

        mana_driver_name = "mana_ib"
        self._check_for_driver(
            node,
            driver_name=mana_driver_name,
            kconfig_variable=self.MANA_IB_KCONFIG,
            dmesg_pattern=self.MANA_IB_DRIVER_MESSAGE_PATTERN,
            verify_module_loads=False,
        )
