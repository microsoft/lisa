# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from typing import Any, Dict, List, Set

from assertpy import assert_that

from lisa import (
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    schema,
    search_space,
    simple_requirement,
)
from lisa.features import Disk
from lisa.features.disks import DiskPremiumSSDLRS, DiskStandardSSDLRS
from lisa.operating_system import BSD, Windows
from lisa.sut_orchestrator import AZURE
from lisa.tools import Dmesg, Fdisk, Lsblk
from lisa.tools.lsblk import DiskInfo
from lisa.tools.pvcreate import Pvcreate
from lisa.tools.pvremove import Pvremove
from lisa.util import LisaException, SkippedException, check_till_timeout


@TestSuiteMetadata(
    area="storage",
    category="functional",
    description="""
    Validates that hot-added data disks are usable by the LVM stack.
    Reproduces a class of host-side NVMe VF failures where
    'Identify NS List failed (status=0xb)' during nvme controller init
    leaves managed-disk namespaces in a bad state, causing pvcreate to
    fail with 'Error reading device ...' and a subsequent lsblk to
    report the affected disks with size 0.
    """,
    owner="rabdulfaizy",
    # TODO(rabdulfaizy): Restore maturity="preview" once the LSG runbook
    # exposes a `-v test_case_maturity:preview` knob so preview-gated
    # tests can be opted in without editing shared tier YAML. Removed
    # for initial bring-up because the upstream selector's stable gate
    # drops any suite whose maturity != "stable" by default.
)
class LvmHotAddSuite(TestSuite):
    _DATA_DISK_SIZE_IN_GB = 10
    _DEFAULT_TIMEOUT = 3600

    # Guest kernel signature of the host-side NVMe VF spec violation:
    #   nvme nvme1: Identify NS List failed (status=0xb)
    # Also match related Identify-family failures so we can surface any
    # bad-status returns from the host NVMe controller; 0xb is the
    # specific fingerprint tracked in the bug that motivated this test.
    _NVME_IDENTIFY_FAIL_REGEX = re.compile(
        r"nvme\s+(?P<ctrl>nvme\d+):\s+Identify[^\n]*?failed\s+"
        r"\(status=(?P<status>0x[0-9a-fA-F]+)\)"
    )
    # Status codes that indicate the host NVMe controller violated the
    # NVMe spec for CNS=02h / CNS=03h Identify commands (see NVMe 1.4
    # sections 5.14.1.10 and 4.6.1). Any of these on a data-disk VF
    # (nvme1 in the tracked repro) means the namespaces are unusable.
    #   0xb  - Invalid Namespace or Format (the primary repro fingerprint)
    #   0x2  - Invalid Field in Command
    #   0xa  - Invalid Format
    _NVME_TRACKED_STATUS_CODES: Set[str] = {"0xb", "0x2", "0xa"}

    @TestCaseMetadata(
        description="""
        Hot-adds ALL remaining standard SSD data disks in a single call
        up to the VM's max_data_disk_count, then runs 'fdisk -l' /
        'pvcreate' on all newly attached devices and re-runs lsblk to
        confirm the devices remain usable. Also scans dmesg for the
        host-side NVMe 'Identify NS List failed (status=0xb)'
        fingerprint.

        Steps:
        1. Snapshot lsblk output.
        2. Hot-add all remaining data disks in one call and verify they
           appear in lsblk with the expected size.
        3. Run 'fdisk -l' and confirm exit code 0.
        4. Run 'pvcreate' on ALL newly attached devices in a single
           command.
        5. Re-run lsblk and confirm each device still reports the
           expected size (did not collapse to 0B).
        6. Scan dmesg for 'nvme nvmeN: Identify ... failed (status=0xb)'
           (and related bad-status codes).

        Parallel mode is the primary repro variant: the burst of
        NS-Changed AENs after a bulk attach floods udev, and pvcreate
        opens the devices before udev has finished populating /sys/,
        matching the 'Udev database has incomplete information about
        device' errors in the originating bug.
        """,
        priority=1,
        timeout=_DEFAULT_TIMEOUT,
        requirement=simple_requirement(
            supported_platform_type=[AZURE],
            unsupported_os=[BSD, Windows],
            disk=DiskStandardSSDLRS(
                # Require SKU capability, not a pre-attached disk. Using
                # 'data_disk_count' here forces LISA to attach N placeholder
                # disks at deploy time and burns LUN 0..N-1, so the test can
                # only hot-add max_data_disk_count - N devices (odd counts,
                # smaller burst). 'max_data_disk_count' filters at capability
                # level so ALL LUNs remain free for the hot-add burst.
                max_data_disk_count=search_space.IntRange(min=1),
            ),
        ),
    )
    def verify_hot_add_disks_pvcreate_parallel_standard_ssd(
        self, node: Node, log: Logger, variables: Dict[str, Any]
    ) -> None:
        self._verify_hot_add_and_pvcreate(
            node=node,
            log=log,
            parallel=True,
            disk_type=schema.DiskType.StandardSSDLRS,
            variables=variables,
        )

    @TestCaseMetadata(
        description="""
        Same as verify_hot_add_disks_pvcreate_parallel_standard_ssd but
        uses premium SSD data disks. Premium SSD is the disk type most
        commonly deployed on the NVMe-controller SKUs (E*ids_v7 /
        Eb*sv6) where the host-side 'Identify NS List failed
        (status=0xb)' bug was originally observed, so this is the
        highest-fidelity repro variant.
        """,
        priority=1,
        timeout=_DEFAULT_TIMEOUT,
        requirement=simple_requirement(
            supported_platform_type=[AZURE],
            unsupported_os=[BSD, Windows],
            disk=DiskPremiumSSDLRS(
                max_data_disk_count=search_space.IntRange(min=1),
            ),
        ),
    )
    def verify_hot_add_disks_pvcreate_parallel_premium_ssd(
        self, node: Node, log: Logger, variables: Dict[str, Any]
    ) -> None:
        self._verify_hot_add_and_pvcreate(
            node=node,
            log=log,
            parallel=True,
            disk_type=schema.DiskType.PremiumSSDLRS,
            variables=variables,
        )

    @TestCaseMetadata(
        description="""
        Hot-adds standard SSD data disks one at a time up to the VM's
        max_data_disk_count, then runs 'fdisk -l' / 'pvcreate' on all
        newly attached devices and re-runs lsblk to confirm the devices
        remain usable. Also scans dmesg for the host-side NVMe
        'Identify NS List failed (status=0xb)' fingerprint.

        Serial mode is a baseline: udev has time between each attach
        to fully process NS-Changed events, so the host-side NVMe VF
        namespace race is less likely to reproduce. This variant
        should almost always pass; a failure indicates a severe form
        of the bug or an unrelated LVM/udev regression.
        """,
        priority=2,
        timeout=_DEFAULT_TIMEOUT,
        requirement=simple_requirement(
            supported_platform_type=[AZURE],
            unsupported_os=[BSD, Windows],
            disk=DiskStandardSSDLRS(
                max_data_disk_count=search_space.IntRange(min=1),
            ),
        ),
    )
    def verify_hot_add_disks_pvcreate_serial_standard_ssd(
        self, node: Node, log: Logger, variables: Dict[str, Any]
    ) -> None:
        self._verify_hot_add_and_pvcreate(
            node=node,
            log=log,
            parallel=False,
            disk_type=schema.DiskType.StandardSSDLRS,
            variables=variables,
        )

    @TestCaseMetadata(
        description="""
        Same as verify_hot_add_disks_pvcreate_serial_standard_ssd but
        uses premium SSD data disks.
        """,
        priority=2,
        timeout=_DEFAULT_TIMEOUT,
        requirement=simple_requirement(
            supported_platform_type=[AZURE],
            unsupported_os=[BSD, Windows],
            disk=DiskPremiumSSDLRS(
                max_data_disk_count=search_space.IntRange(min=1),
            ),
        ),
    )
    def verify_hot_add_disks_pvcreate_serial_premium_ssd(
        self, node: Node, log: Logger, variables: Dict[str, Any]
    ) -> None:
        self._verify_hot_add_and_pvcreate(
            node=node,
            log=log,
            parallel=False,
            disk_type=schema.DiskType.PremiumSSDLRS,
            variables=variables,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _verify_hot_add_and_pvcreate(
        self,
        node: Node,
        log: Logger,
        parallel: bool,
        disk_type: schema.DiskType,
        variables: Dict[str, Any],
    ) -> None:
        # --- Arrange ---
        disk = node.features[Disk]
        lsblk = node.tools[Lsblk]
        fdisk = node.tools[Fdisk]
        pvcreate = node.tools[Pvcreate]
        pvremove = node.tools[Pvremove]
        dmesg = node.tools[Dmesg]

        assert node.capability.disk, "node.capability.disk must be set"
        assert isinstance(node.capability.disk.max_data_disk_count, int)
        assert isinstance(node.capability.disk.data_disk_count, int)
        max_data_disk_count = node.capability.disk.max_data_disk_count
        current_data_disk_count = node.capability.disk.data_disk_count
        free_luns = list(range(current_data_disk_count, max_data_disk_count))
        if not free_luns:
            raise SkippedException(
                "No free LUNs available for hot-add. "
                "Consider setting max_data_disk_count in the runbook."
            )

        # Optional runbook cap: '-v max_disks_to_add:N' limits the hot-add
        # burst to the first N free LUNs. Default (0/unset) uses ALL free
        # LUNs up to max_data_disk_count, which is the highest-fidelity
        # repro of the host-side NVMe VF Identify-NS-List race. Use this
        # knob to isolate whether a failure is disk-count-sensitive or
        # to shorten runs during triage on VM sizes with very large
        # max_data_disk_count.
        requested_cap = int(variables.get("max_disks_to_add", 0) or 0)
        if 0 < requested_cap < len(free_luns):
            log.info(
                f"Runbook 'max_disks_to_add={requested_cap}' caps the "
                f"hot-add burst from {len(free_luns)} to {requested_cap} "
                f"disk(s)."
            )
            free_luns = free_luns[:requested_cap]

        log.info(
            f"disk_type={disk_type}, parallel={parallel}, "
            f"max_data_disk_count={max_data_disk_count}, "
            f"current_data_disk_count={current_data_disk_count}, "
            f"free_luns={free_luns}"
        )

        baseline_disks = lsblk.get_disks(force_run=True)
        baseline_names = {d.name for d in baseline_disks}
        size_in_gb = self._DATA_DISK_SIZE_IN_GB
        disks_added: List[str] = []
        new_device_paths: List[str] = []

        try:
            # --- Act: hot-add ---
            if parallel:
                log.info(f"Hot-adding {len(free_luns)} data disks in parallel")
                disks_added = list(
                    disk.add_data_disk(len(free_luns), disk_type, size_in_gb)
                )
                new_device_paths = self._wait_for_new_devices(
                    lsblk=lsblk,
                    baseline_names=baseline_names,
                    expected_count=len(free_luns),
                    size_in_gb=size_in_gb,
                    log=log,
                )
            else:
                for lun in free_luns:
                    log.info(f"Hot-adding data disk at LUN {lun}")
                    added = disk.add_data_disk(1, disk_type, size_in_gb, lun)
                    disks_added.extend(added)
                    new_device_paths = self._wait_for_new_devices(
                        lsblk=lsblk,
                        baseline_names=baseline_names,
                        expected_count=len(disks_added),
                        size_in_gb=size_in_gb,
                        log=log,
                    )

            log.info(f"Newly attached devices: {new_device_paths}")

            # --- Act: 'fdisk -l' listing ---
            # Matches the manual repro's diagnostic step; also verifies the
            # kernel can enumerate partition tables on the new devices.
            fdisk_result = fdisk.run("-l", sudo=True, force_run=True)
            fdisk_result.assert_exit_code(
                0,
                f"'fdisk -l' failed after hot-add. stderr: {fdisk_result.stderr}",
            )
            for device_path in new_device_paths:
                fdisk_msg = (
                    f"'fdisk -l' output should list hot-added device {device_path}"
                )
                assert_that(fdisk_result.stdout).described_as(fdisk_msg).contains(
                    device_path
                )

            # --- Act: pvcreate on ALL new devices in one command ---
            log.info(
                f"Running pvcreate on {len(new_device_paths)} devices: "
                f"{new_device_paths}"
            )
            # Pvcreate.create_pv() enforces exit code 0; a failure here means
            # LVM could not read the device (the primary bug fingerprint).
            pvcreate.create_pv(*new_device_paths)

            # --- Assert: sizes did not collapse to 0 after pvcreate ---
            post_disks: Dict[str, DiskInfo] = {
                d.name: d for d in lsblk.get_disks(force_run=True)
            }
            zero_sized: List[str] = []
            missing: List[str] = []
            for device_path in new_device_paths:
                dev_name = device_path.rsplit("/", 1)[-1]
                disk_info = post_disks.get(dev_name)
                if disk_info is None:
                    missing.append(device_path)
                    continue
                if disk_info.size_in_gb == 0:
                    zero_sized.append(device_path)

            if missing:
                missing_msg = (
                    f"Hot-added device(s) {missing} disappeared from "
                    "lsblk after pvcreate. This matches the host-side "
                    "NVMe VF namespace-collapse failure tracked in the "
                    "originating bug."
                )
                raise LisaException(missing_msg)
            zero_sized_msg = (
                "The following hot-added devices reported size 0 in lsblk "
                "after pvcreate, which indicates the host NVMe VF "
                "namespaces collapsed. This is the fingerprint of the "
                "host-side 'Identify NS List failed (status=0xb)' bug."
            )
            assert_that(zero_sized).described_as(zero_sized_msg).is_empty()

            # --- Assert: no tracked NVMe Identify failures in dmesg ---
            self._assert_no_tracked_nvme_identify_failures(dmesg, log)

        finally:
            # --- Cleanup ---
            if new_device_paths:
                log.debug(f"Cleanup: running pvremove on {new_device_paths}")
                try:
                    pvremove.remove_pv(*new_device_paths, ignore_errors=True)
                except Exception as ex:  # noqa: BLE001
                    log.warning(f"pvremove cleanup raised: {ex}")
            if disks_added:
                log.debug(f"Cleanup: removing data disks {disks_added}")
                try:
                    disk.remove_data_disk(disks_added)
                except Exception as ex:  # noqa: BLE001
                    log.warning(f"remove_data_disk cleanup raised: {ex}")

    def _wait_for_new_devices(
        self,
        lsblk: Lsblk,
        baseline_names: Set[str],
        expected_count: int,
        size_in_gb: int,
        log: Logger,
    ) -> List[str]:
        # Poll lsblk until the expected number of new block devices appear;
        # udev / nvme rescan can lag behind the hot-add ARM operation.
        state: Dict[str, List[DiskInfo]] = {"added": []}

        def _check() -> bool:
            state["added"] = [
                d
                for d in lsblk.get_disks(force_run=True)
                if d.name not in baseline_names
            ]
            return len(state["added"]) >= expected_count

        check_till_timeout(
            _check,
            timeout_message=(
                f"expected {expected_count} new disk(s) in lsblk after "
                f"hot-add, found {len(state['added'])}: "
                f"{[d.name for d in state['added']]}"
            ),
            timeout=60,
            interval=2,
        )
        added_disks: List[DiskInfo] = state["added"]
        assert_that(added_disks).described_as(
            f"expected {expected_count} hot-added disks in lsblk"
        ).is_length(expected_count)
        for d in added_disks:
            size_msg = f"hot-added device {d.device_name} should be {size_in_gb} GB"
            assert_that(d.size_in_gb).described_as(size_msg).is_equal_to(size_in_gb)
        log.debug(f"Detected new devices: {[d.device_name for d in added_disks]}")
        return [d.device_name for d in added_disks]

    def _assert_no_tracked_nvme_identify_failures(
        self, dmesg: Dmesg, log: Logger
    ) -> None:
        dmesg_out = dmesg.get_output(force_run=True)
        matches = list(self._NVME_IDENTIFY_FAIL_REGEX.finditer(dmesg_out))
        if not matches:
            log.info("No 'nvme <ctrl>: Identify ... failed' messages found in dmesg.")
            return

        tracked: List[str] = []
        other: List[str] = []
        for m in matches:
            line = m.group(0)
            status = m.group("status").lower()
            if status in self._NVME_TRACKED_STATUS_CODES:
                tracked.append(line)
            else:
                other.append(line)

        if other:
            log.warning(
                f"Non-tracked NVMe Identify failures observed in dmesg "
                f"(count={len(other)}); first: {other[0]}"
            )

        tracked_msg = (
            "Guest kernel logged NVMe 'Identify ... failed' with a "
            "status code that indicates the host controller returned an "
            "invalid response to a spec-compliant Identify command (per "
            "NVMe 1.4 sec 4.6.1 / 5.14.1.10). Status 0xb is the "
            "fingerprint of the host-side NVMe VF spec violation. "
            f"Offending lines: {tracked}"
        )
        assert_that(tracked).described_as(tracked_msg).is_empty()

    def after_case(self, log: Logger, **kwargs: Any) -> None:
        # Per-test cleanup is done in each test's finally block; nothing
        # additional required here.
        pass
