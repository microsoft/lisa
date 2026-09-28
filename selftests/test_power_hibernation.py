# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""
Local, mock-based regression tests for the hibernation verification logic in
``lisa.microsoft.testsuites.power.common``.

These reproduce, without any Azure VM, the two distinct failure signatures seen
in the pipeline logs:

* Run 158744729 -- every case fresh-booted (boot time before != after), i.e.
  hibernation genuinely did not happen. The test must FAIL.
* Run 158745077 -- hibernation worked (boot time before == after) but the
  cumulative "hibernation entry" marker count increased by 2 on SLES. With the
  old ``== 1`` assertion the test wrongly FAILED; with the ``>= 1`` assertion it
  must PASS.

They also cover the VMHibernateFailed retry double-count and the SR-IOV NIC
re-enumeration race.
"""

from typing import Iterator, List
from unittest import TestCase
from unittest.mock import MagicMock, patch

from lisa.features import StartStop
from lisa.features.startstop import VMStatus
from lisa.microsoft.testsuites.power import common as power_common
from lisa.tools import Dmesg, HibernationSetup, Who


class _FakeHibernationSetup:
    """Simulates HibernationSetup marker counts across a hibernation cycle.

    ``entry_counts`` etc. are the successive integer values returned by
    ``check_*`` -- the first call is the pre-cycle baseline and the second is
    the post-resume count.
    """

    def __init__(
        self,
        entry_counts: List[int],
        exit_counts: List[int],
        received_counts: List[int],
        uevent_counts: List[int],
    ) -> None:
        self._entry: Iterator[int] = iter(entry_counts)
        self._exit: Iterator[int] = iter(exit_counts)
        self._received: Iterator[int] = iter(received_counts)
        self._uevent: Iterator[int] = iter(uevent_counts)
        self.start = MagicMock()

    def check_entry(self) -> int:
        return next(self._entry)

    def check_exit(self) -> int:
        return next(self._exit)

    def check_received(self) -> int:
        return next(self._received)

    def check_uevent(self) -> int:
        return next(self._uevent)

    def get_hibernate_resume_offset_from_hibfile(self) -> str:
        return "524301"

    def get_hibernate_resume_offset_from_cmd(self) -> str:
        return "524301"

    def get_hibernate_resume_offset_from_sys_power(self) -> str:
        return "524301"


class HibernationByToolTestCase(TestCase):
    def setUp(self) -> None:
        # Silence the real deallocation-wait sleep.
        self._sleep_patch = patch.object(power_common, "sleep")
        self._sleep_patch.start()
        self.addCleanup(self._sleep_patch.stop)

    def _build_node(
        self,
        hib_tool: _FakeHibernationSetup,
        boot_before: str,
        boot_after: str,
        pci_nics_sequence: List[List[str]],
        nic_names_sequence: List[List[str]],
    ) -> MagicMock:
        node = MagicMock()

        # os is a bare mock; type(node.os) is not a known distro, so
        # _perform_hibernation_cycle skips the reboot branch.
        who = MagicMock()
        who.last_boot.side_effect = [boot_before, boot_after]

        dmesg = MagicMock()

        node.tools = {
            HibernationSetup: hib_tool,
            Dmesg: dmesg,
            Who: who,
        }

        startstop = MagicMock()
        startstop.get_status.return_value = VMStatus.Deallocated
        node.features = {StartStop: startstop}

        nics = MagicMock()
        nics.get_pci_nics.side_effect = list(pci_nics_sequence)
        nics.get_nic_names.side_effect = list(nic_names_sequence)
        node.nics = nics

        return node

    def test_hibernation_worked_marker_overcount_passes(self) -> None:
        """Run 158745077: hibernation worked, SLES logged the marker twice.

        boot time before == after and every marker delta is 2. The ``>= 1``
        assertion must accept this.
        """
        hib = _FakeHibernationSetup(
            entry_counts=[5, 7],  # delta 2
            exit_counts=[5, 7],
            received_counts=[5, 7],
            uevent_counts=[5, 7],
        )
        node = self._build_node(
            hib,
            boot_before="2026-09-26 15:12:00",
            boot_after="2026-09-26 15:12:00",
            # baseline + one post-resume reload attempt, counts match (1 == 1)
            pci_nics_sequence=[["eth0"], ["eth0"]],
            nic_names_sequence=[["eth0"], ["eth0"]],
        )

        # Should not raise.
        power_common.verify_hibernation_by_tool(node, MagicMock())

    def test_fresh_boot_marker_delta_zero_fails(self) -> None:
        """Run 158744729: VM fresh-booted, hibernation never happened.

        boot time before != after and the marker delta is 0. The boot-time
        check (now first) must fail the test.
        """
        hib = _FakeHibernationSetup(
            entry_counts=[3, 3],  # delta 0
            exit_counts=[3, 3],
            received_counts=[3, 3],
            uevent_counts=[3, 3],
        )
        node = self._build_node(
            hib,
            boot_before="2026-09-26 15:02:00",
            boot_after="2026-09-26 15:04:00",  # differs -> fresh boot
            pci_nics_sequence=[["eth0"], ["eth0"]],
            nic_names_sequence=[["eth0"], ["eth0"]],
        )

        with self.assertRaises(AssertionError) as ctx:
            power_common.verify_hibernation_by_tool(node, MagicMock())
        self.assertIn("boot time before hibernation", str(ctx.exception))

    def test_retry_double_count_passes(self) -> None:
        """A retried VMHibernateFailed can log the markers twice; delta 2 is ok."""
        hib = _FakeHibernationSetup(
            entry_counts=[0, 2],
            exit_counts=[0, 2],
            received_counts=[0, 2],
            uevent_counts=[0, 2],
        )
        node = self._build_node(
            hib,
            boot_before="2026-09-26 10:26:00",
            boot_after="2026-09-26 10:26:00",
            pci_nics_sequence=[["eth0"], ["eth0"]],
            nic_names_sequence=[["eth0"], ["eth0"]],
        )

        power_common.verify_hibernation_by_tool(node, MagicMock())

    def test_worked_but_no_marker_fails(self) -> None:
        """Hibernation-looked-ok boot time but zero markers still fails (>= 1)."""
        hib = _FakeHibernationSetup(
            entry_counts=[4, 4],  # delta 0
            exit_counts=[4, 5],
            received_counts=[4, 5],
            uevent_counts=[4, 5],
        )
        node = self._build_node(
            hib,
            boot_before="2026-09-26 15:12:00",
            boot_after="2026-09-26 15:12:00",
            pci_nics_sequence=[["eth0"], ["eth0"]],
            nic_names_sequence=[["eth0"], ["eth0"]],
        )

        with self.assertRaises(AssertionError) as ctx:
            power_common.verify_hibernation_by_tool(node, MagicMock())
        self.assertIn("hibernation entry", str(ctx.exception))


class NicCountRetryTestCase(TestCase):
    def test_transient_missing_vf_recovers(self) -> None:
        """The SR-IOV VF is briefly absent after resume, then re-enumerates.

        The bounded retry in _verify_common_hibernation_requirements must
        reload and re-check until the counts converge, rather than failing on
        the first racy read.
        """
        node = MagicMock()
        dmesg = MagicMock()
        node.tools = {Dmesg: dmesg}

        nics = MagicMock()
        # First reload -> VF missing (0 pci nics); second -> VF back (1).
        nics.get_pci_nics.side_effect = [[], ["enP1"]]
        nics.get_nic_names.side_effect = [["eth0"], ["eth0"]]
        node.nics = nics

        with patch("lisa.microsoft.testsuites.power.common.sleep"), patch(
            "retry.api.time.sleep"
        ):
            power_common._verify_common_hibernation_requirements(
                node,
                MagicMock(),
                boot_time_before="2026-09-26 15:12:00",
                boot_time_after="2026-09-26 15:12:00",
                lower_nics_before=["enP1"],
                upper_nics_before=["eth0"],
            )

        # reload retried at least twice before converging.
        self.assertGreaterEqual(nics.reload.call_count, 2)

    def test_permanent_nic_loss_still_fails(self) -> None:
        """A genuine, permanent NIC loss must still fail after the retries."""
        node = MagicMock()
        node.tools = {Dmesg: MagicMock()}

        nics = MagicMock()
        nics.get_pci_nics.return_value = []  # never comes back
        nics.get_nic_names.return_value = ["eth0"]
        node.nics = nics

        with patch("lisa.microsoft.testsuites.power.common.sleep"), patch(
            "retry.api.time.sleep"
        ), self.assertRaises(AssertionError) as ctx:
            power_common._verify_common_hibernation_requirements(
                node,
                MagicMock(),
                boot_time_before="2026-09-26 15:12:00",
                boot_time_after="2026-09-26 15:12:00",
                lower_nics_before=["enP1"],
                upper_nics_before=["eth0"],
            )
        self.assertIn("sriov nics count", str(ctx.exception))
