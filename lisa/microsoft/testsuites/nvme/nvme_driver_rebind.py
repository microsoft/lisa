# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Any, List

from assertpy import assert_that

from lisa import (
    Logger,
    Node,
    SkippedException,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.features import Nvme
from lisa.tools import Dmesg, Echo, Fdisk, Lspci, Mkfs, Mount, Nvmecli
from lisa.tools.mkfs import FileSystem
from lisa.util import LisaException, check_till_timeout
from lisa.util.constants import DEVICE_TYPE_NVME

# Sysfs path template for PCI driver unbind/bind.
_DRIVER_UNBIND_PATH = "/sys/bus/pci/drivers/{driver}/unbind"
_DRIVER_BIND_PATH = "/sys/bus/pci/drivers/{driver}/bind"


def _get_non_os_nvme_slots(node: Node, log: Logger) -> List[str]:
    """Return PCI slots of NVMe devices that are NOT backing the OS disk."""
    nvme = node.features[Nvme]
    lspci = node.tools[Lspci]

    all_nvme_slots = lspci.get_device_names_by_type(DEVICE_TYPE_NVME, force_run=True)
    if not all_nvme_slots:
        raise SkippedException("No NVMe PCI devices found via lspci.")

    # Determine the OS-disk controller so we never unbind it.
    try:
        os_controller = nvme.get_nvme_os_disk_controller()
    except LisaException:
        os_controller = ""

    if os_controller:
        os_slot = lspci.get_pci_slot_from_device_path(os_controller)
        log.debug(f"OS NVMe controller {os_controller} at slot {os_slot}")
    else:
        os_slot = None

    safe_slots = [s for s in all_nvme_slots if s != os_slot]
    if not safe_slots:
        raise SkippedException(
            "All NVMe devices belong to the OS disk; "
            "cannot safely unbind any device."
        )
    return safe_slots


@TestSuiteMetadata(
    area="nvme",
    category="functional",
    description="""
    Validates NVMe driver unbind/rebind recovery.
    Verifies device rediscovery, data integrity, and absence of
    driver or I/O errors after rebinding.
    """,
    owner="Microsoft",
)
class NvmeDriverRebind(TestSuite):
    """Tests for NVMe PCI driver unbind and rebind scenarios."""

    _TEST_TIMEOUT = 1800

    @TestCaseMetadata(
        description="""
        Verify that an NVMe device can be detached from and reattached to
        the Linux NVMe driver via sysfs without data loss or errors.

        Steps:
        1. Identify a non-OS NVMe device and its PCI slot / driver.
        2. Write a known data pattern to the device and record its md5sum.
        3. Unmount the filesystem and unbind the driver via sysfs.
        4. Rebind the driver and wait for the namespace to reappear.
        5. Remount, verify data integrity via md5sum comparison.
        6. Perform a fresh write/read to confirm ongoing I/O capability.
        7. Check dmesg for NVMe-related errors.
        """,
        priority=2,
        timeout=1800,
        requirement=simple_requirement(
            supported_features=[Nvme],
        ),
    )
    def verify_nvme_driver_unbind_rebind(self, node: Node, log: Logger) -> None:
        safe_slots = _get_non_os_nvme_slots(node, log)
        target_slot = safe_slots[0]

        lspci = node.tools[Lspci]
        nvme = node.features[Nvme]
        mount_tool = node.tools[Mount]
        echo = node.tools[Echo]
        nvme_cli = node.tools[Nvmecli]

        # --- Arrange ---
        driver_name = lspci.get_used_module(target_slot)
        assert_that(driver_name).described_as(
            f"No kernel driver bound to NVMe slot {target_slot}."
        ).is_not_empty()
        log.info(f"Target NVMe slot {target_slot}, driver: {driver_name}")

        # Pick the first raw (non-OS) NVMe namespace for data testing.
        namespaces_before = nvme.get_raw_nvme_disks()
        assert_that(namespaces_before).described_as(
            "No raw NVMe namespaces available for testing."
        ).is_not_empty()
        namespace = namespaces_before[0]
        log.info(f"Using namespace {namespace} for data integrity test.")

        # Get the NVMe error count before the operation.
        error_count_before = nvme_cli.get_error_count(namespace)

        # Format, mount, and write test data.
        mount_point = namespace.rpartition("/")[-1]
        mount_tool.umount(namespace, mount_point)

        node.tools[Fdisk].delete_partitions(namespace)
        node.tools[Mkfs].mkfs(namespace, FileSystem.ext4)
        mount_tool.mount(namespace, mount_point)

        # Write a 100 MB test file and compute its checksum.
        data_file = f"{mount_point}/rebind_test_data"
        node.execute(
            f"dd if=/dev/urandom of={data_file} bs=1M count=100",
            shell=True,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "Failed to write test data before unbind."
            ),
        )
        md5_before_result = node.execute(
            f"md5sum {data_file}",
            shell=True,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "Failed to compute md5sum before unbind."
            ),
        )
        md5_before = md5_before_result.stdout.split()[0]
        log.info(f"md5sum before unbind: {md5_before}")

        # Record dmesg cursor for later error checks.
        dmesg_before = node.tools[Dmesg].get_output(force_run=True)
        dmesg_line_count_before = len(dmesg_before.splitlines())

        # --- Act: Unbind ---
        mount_tool.umount(namespace, mount_point, erase=False)
        log.info(f"Unbinding driver '{driver_name}' from slot {target_slot}")
        unbind_path = _DRIVER_UNBIND_PATH.format(driver=driver_name)
        echo.write_to_file(
            target_slot,
            node.get_pure_path(unbind_path),
            sudo=True,
        )

        # Verify the device disappeared from lspci driver binding.
        post_unbind_driver = lspci.get_used_module(target_slot)
        assert_that(post_unbind_driver).described_as(
            f"Driver should be unbound from slot {target_slot} "
            "but a driver is still reported."
        ).is_empty()
        log.info("Driver successfully unbound.")

        # --- Act: Rebind ---
        log.info(f"Rebinding driver '{driver_name}' to slot {target_slot}")
        bind_path = _DRIVER_BIND_PATH.format(driver=driver_name)
        echo.write_to_file(
            target_slot,
            node.get_pure_path(bind_path),
            sudo=True,
        )

        # Wait for the namespace to reappear.
        def _namespace_exists() -> bool:
            result = node.execute(f"test -b {namespace}", shell=True, sudo=True)
            return bool(result.exit_code == 0)

        check_till_timeout(
            _namespace_exists,
            timeout_message=(
                f"Namespace {namespace} did not reappear within 60s "
                "after driver rebind."
            ),
            timeout=60,
            interval=2,
        )
        log.info(f"Namespace {namespace} reappeared after rebind.")

        # Verify PCI device has the driver bound again.
        rebound_driver = lspci.get_used_module(target_slot)
        assert_that(rebound_driver).described_as(
            f"Expected driver '{driver_name}' to be rebound to "
            f"slot {target_slot}, but got '{rebound_driver}'."
        ).is_equal_to(driver_name)

        # Verify NVMe device count is the same as before.
        namespaces_after = nvme.get_raw_nvme_disks()
        assert_that(namespaces_after).described_as(
            "NVMe namespace count changed after driver rebind."
        ).is_length(len(namespaces_before))

        # --- Assert: Data integrity ---
        mount_tool.mount(namespace, mount_point)
        md5_after_result = node.execute(
            f"md5sum {data_file}",
            shell=True,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "Failed to compute md5sum after rebind."
            ),
        )
        md5_after = md5_after_result.stdout.split()[0]
        log.info(f"md5sum after rebind: {md5_after}")
        assert_that(md5_after).described_as(
            "Data integrity check failed: md5sum mismatch after "
            "NVMe driver unbind/rebind."
        ).is_equal_to(md5_before)

        # --- Assert: Post-rebind I/O capability ---
        verify_file = f"{mount_point}/rebind_verify_io"
        node.execute(
            f"dd if=/dev/urandom of={verify_file} bs=1M count=10",
            shell=True,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=("Post-rebind I/O write failed."),
        )
        node.execute(
            f"dd if={verify_file} of=/dev/null bs=1M",
            shell=True,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=("Post-rebind I/O read failed."),
        )
        log.info("Post-rebind I/O write and read succeeded.")

        # --- Assert: No NVMe errors in dmesg ---
        dmesg_after = node.tools[Dmesg].get_output(force_run=True)
        new_dmesg_lines = dmesg_after.splitlines()[dmesg_line_count_before:]
        nvme_error_keywords = [
            "nvme nvme",
            "I/O error",
            "blk_update_request",
            "EXT4-fs error",
        ]
        error_lines = [
            line
            for line in new_dmesg_lines
            if any(kw in line for kw in nvme_error_keywords) and "error" in line.lower()
        ]
        assert_that(error_lines).described_as(
            "NVMe or I/O errors detected in dmesg after driver rebind: "
            + "; ".join(error_lines[:5])
        ).is_empty()

        # --- Assert: NVMe error count did not increase ---
        error_count_after = nvme_cli.get_error_count(namespace)
        assert_that(error_count_after).described_as(
            f"NVMe error count increased from {error_count_before} "
            f"to {error_count_after} after driver rebind."
        ).is_equal_to(error_count_before)

        log.info("NVMe driver unbind/rebind recovery verified.")

        # Cleanup
        mount_tool.umount(namespace, mount_point)

    def after_case(self, log: Logger, **kwargs: Any) -> None:
        """Ensure NVMe devices are rescanned after test completion."""
        node = kwargs.get("node")
        if node is not None:
            # PCI rescan to recover any devices left unbound.
            node.tools[Echo].write_to_file(
                "1",
                node.get_pure_path("/sys/bus/pci/rescan"),
                sudo=True,
            )
            log.debug("PCI rescan triggered in after_case cleanup.")
