import re

from lisa import (
    LisaException,
    Node,
    SkippedException,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.operating_system import Posix
from lisa.sut_orchestrator import AZURE
from lisa.tools import Dmesg, KernelConfig, Modprobe


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

    @TestCaseMetadata(
        description="""
        This test case checks for the mana ethernet driver.
        """,
        priority=4,
        requirement=simple_requirement(
            supported_platform_type=[AZURE], supported_os=[Posix]
        ),
    )
    def verify_mana_en_driver_present(self, node: Node) -> None:
        if not node.nics.is_mana_present():
            raise SkippedException(
                "MANA driver tests should be run in a MANA VM environment"
            )

        mana_driver_name = "mana"
        dmesg = node.tools[Dmesg]
        modprobe = node.tools[Modprobe]
        kconfig = node.tools[KernelConfig]
        kernel_driver_output = dmesg.get_output(force_run=True)
        # Check kconfig for mana
        mana_is_builtin = kconfig.is_built_in(mana_driver_name)
        mana_is_module = kconfig.is_built_as_module(mana_driver_name)
        if mana_is_builtin:
            node.log.info(f"{mana_driver_name} is reported as builtin in kconfig")
        elif mana_is_module:
            node.log.info(
                f"{mana_driver_name} is reported as a loadable kernel module in kconfig"
            )
        else:
            node.log.warn(
                f"{mana_driver_name} is not in kconfig for this image, checking if driver is present (possible out of tree build)"
            )

        # check modprobe for loadable module
        # if module is available (and not a builtin or loaded already), load the module
        # this will throw if the module isn't found.
        if modprobe.module_exists(mana_driver_name) and not (
            mana_is_builtin or modprobe.is_module_loaded(mana_driver_name)
        ):
            node.log.info(
                f"Attempting to load {mana_driver_name} driver with modprobe..."
            )
            modprobe.load(mana_driver_name)

        # finally, verify that mana logs are present after loading.
        matches = self.MANA_DRIVER_MESSAGE_PATTERN.search(kernel_driver_output)
        if not matches:
            raise LisaException(
                (
                    f"{mana_driver_name} driver reported as present but "
                    f"no {mana_driver_name} logs in driver messages."
                )
            )

    @TestCaseMetadata(
        description="""
        This test case checks for the mana ethernet driver.
        """,
        priority=4,
        requirement=simple_requirement(
            supported_platform_type=[AZURE], supported_os=[Posix]
        ),
    )
    def verify_mana_ib_driver_present(self, node: Node) -> None:
        if not node.nics.is_mana_present():
            raise SkippedException(
                "MANA driver tests should be run in a MANA VM environment"
            )

        mana_driver_name = "mana_ib"
        dmesg = node.tools[Dmesg]
        modprobe = node.tools[Modprobe]
        kconfig = node.tools[KernelConfig]
        kernel_driver_output = dmesg.get_output(force_run=True)

        # Check kconfig for mana
        mana_is_builtin = kconfig.is_built_in(mana_driver_name)
        mana_is_module = kconfig.is_built_as_module(mana_driver_name)
        if mana_is_builtin:
            node.log.info(f"{mana_driver_name} is reported as builtin in kconfig")
        elif mana_is_module:
            node.log.info(
                f"{mana_driver_name} is reported as a loadable kernel module in kconfig"
            )
        else:
            node.log.warn(
                (
                    f"{mana_driver_name} is not in kconfig for this image, "
                    "checking if driver is present (possible out of tree build)"
                )
            )

        # check modprobe for loadable module
        # if module is available (and not a builtin or loaded already), load the module
        # this will throw if the module isn't found.
        if modprobe.module_exists(mana_driver_name) and not (
            mana_is_builtin or modprobe.is_module_loaded(mana_driver_name)
        ):
            node.log.info(
                f"Attempting to load {mana_driver_name} driver with modprobe..."
            )
            modprobe.load(mana_driver_name)

        # finally, verify that mana logs are present after loading.
        matches = self.MANA_IB_DRIVER_MESSAGE_PATTERN.search(kernel_driver_output)
        if not matches:
            raise LisaException(
                (
                    f"{mana_driver_name} driver reported as present but "
                    f"no {mana_driver_name} logs in driver messages."
                )
            )
