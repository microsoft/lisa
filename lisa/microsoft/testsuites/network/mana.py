# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from assertpy import assert_that

from lisa import (
    Node,
    SkippedException,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    features,
    simple_requirement,
)
from lisa.operating_system import BSD, Windows
from lisa.sut_orchestrator import AZURE
from lisa.tools import Lsmod, PowerShell


@TestSuiteMetadata(
    area="mana",
    category="functional",
    description="""
    This test suite verifies that the MANA (Microsoft Azure Network Adapter)
    driver is present and bound when the platform exposes a MANA VF to the
    guest, so AccelNet/SR-IOV is actually available instead of silently falling
    back to the synthetic datapath.

    It closes the gap from ICM 809802825, where an AzureLinux 3.0 kernel-mshv
    build shipped without CONFIG_MICROSOFT_MANA: the MANA VF (1414:00ba) was
    orphaned on the PCI bus and the VM ran on synthetic networking only, while
    platform monitoring still reported the VM as healthy.
    """,
)
class Mana(TestSuite):
    @TestCaseMetadata(
        description="""
        This case verifies that when the platform exposes a MANA (Microsoft
        Azure Network Adapter) VF to a Linux guest, the MANA driver is present
        and bound, so AccelNet/SR-IOV is actually available instead of silently
        falling back to the synthetic hv_netvsc datapath.

        This closes the gap from ICM 809802825, where an AzureLinux 3.0
        kernel-mshv build shipped without CONFIG_MICROSOFT_MANA: the MANA VF
        (1414:00ba) was orphaned on the PCI bus and the VM ran on synthetic
        networking only, while platform monitoring still reported the VM as
        healthy.

        Steps,
        1. Reload NIC info and detect whether a MANA VF is exposed to the guest.
           If no MANA device is present, skip (test only applies to MANA SKUs).
        2. Assert the running kernel is built with CONFIG_MICROSOFT_MANA enabled.
        3. Assert the mana kernel module is loaded (the VF is bound, not
           orphaned on the PCI bus).
        4. Assert the MANA VF is paired with a synthetic NIC, i.e. the
           accelerated datapath is established.
        """,
        priority=2,
        requirement=simple_requirement(
            network_interface=features.Sriov(),
            supported_platform_type=[AZURE],
            unsupported_os=[BSD, Windows],
        ),
    )
    def verify_mana_driver_present(self, node: Node) -> None:
        node.nics.reload()
        if not node.nics.is_mana_device_present():
            raise SkippedException(
                "No MANA VF (1414:00ba) is exposed to this VM; this test only "
                "applies to SKUs where the platform attaches a MANA adapter."
            )

        # ICM 809802825: the kernel-mshv flavor shipped with
        # CONFIG_MICROSOFT_MANA disabled, so no driver could bind the MANA VF.
        assert_that(node.nics.is_mana_driver_enabled()).described_as(
            "A MANA VF is exposed to the VM but CONFIG_MICROSOFT_MANA is not "
            "enabled in the running kernel. The VF will be orphaned and "
            "AccelNet will be unavailable (regression from ICM 809802825)."
        ).is_true()

        # The mana module must actually be loaded, i.e. the VF is bound and not
        # sitting orphaned on the PCI bus.
        assert_that(
            node.tools[Lsmod].module_exists("mana", force_run=True)
        ).described_as(
            "CONFIG_MICROSOFT_MANA is enabled but the 'mana' module is not "
            "loaded; the MANA VF is not bound and the VM is running on "
            "synthetic networking only."
        ).is_true()

        # The MANA VF must be paired with a synthetic NIC so the accelerated
        # datapath is in use rather than hv_netvsc alone.
        paired_vf_nics = [nic for nic in node.nics.nics.values() if nic.lower]
        assert_that(paired_vf_nics).described_as(
            "No synthetic NIC is paired with a MANA VF; the accelerated "
            "datapath is not established and traffic falls back to hv_netvsc."
        ).is_not_empty()

    @TestCaseMetadata(
        description="""
        This case verifies the Windows-guest equivalent of the MANA
        driver-presence check. When the platform exposes a MANA VF
        (PCI VEN_1414 & DEV_00BA) to a Windows guest, the Microsoft Azure
        Network Adapter driver must be installed and running so the device is
        not left orphaned (the Windows analog of ICM 809802825).

        Steps,
        1. Query PnP devices for the MANA VF hardware id (VEN_1414&DEV_00BA).
           If none is present, skip (test only applies to MANA SKUs).
        2. Assert every MANA VF device reports Status 'OK', i.e. a driver is
           bound and running rather than the device being orphaned / in error.
        """,
        priority=2,
        requirement=simple_requirement(
            network_interface=features.Sriov(),
            supported_platform_type=[AZURE],
            supported_os=[Windows],
        ),
    )
    def verify_mana_driver_present_windows(self, node: Node) -> None:
        if not isinstance(node.os, Windows):
            raise SkippedException("This test is intended for Windows guests only.")

        powershell = node.tools[PowerShell]
        devices = powershell.run_cmdlet(
            "Get-PnpDevice -PresentOnly | "
            "Where-Object { $_.InstanceId -match 'VEN_1414&DEV_00BA' } | "
            "Select-Object Status, Class, FriendlyName, InstanceId",
            output_json=True,
            fail_on_error=False,
        )
        if not devices:
            raise SkippedException(
                "No MANA VF (VEN_1414&DEV_00BA) is exposed to this VM; this "
                "test only applies to SKUs where the platform attaches a MANA "
                "adapter."
            )

        # ConvertTo-Json emits a single object for one device and a list for
        # many; normalize to a list.
        if isinstance(devices, dict):
            devices = [devices]

        for device in devices:
            assert_that(device.get("Status")).described_as(
                f"MANA VF {device.get('InstanceId')} reports status "
                f"'{device.get('Status')}' instead of 'OK'; the Microsoft "
                "Azure Network Adapter driver is not bound and the device is "
                "orphaned (Windows analog of ICM 809802825)."
            ).is_equal_to("OK")
