# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Any, List

from assertpy import assert_that

from lisa import (
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.features import Nvme
from lisa.tools import Dmesg, Echo, Lspci, Mkfs, Mount, Nvmecli
from lisa.tools.fdisk import FileSystem
from lisa.util.constants import DEVICE_TYPE_NVME


def _write_test_data(
    node: Node,
    namespace: str,
    mount_point: str,
    log: Logger,
) -> str:
    """Format, mount, write test data, and return the md5sum of the file."""
    mkfs = node.tools[Mkfs]
    mount = node.tools[Mount]

    # Ensure clean state.
    mount.umount(namespace, mount_point)

    # Format directly (no partition table) and mount.
    mkfs.mkfs(namespace, FileSystem.ext4)
    mount.mount(namespace, mount_point)

    # Write a 100 MB file with deterministic content.
    log.debug(f"Writing test data to {mount_point}/data ...")
    cmd_result = node.execute(
        f"dd if=/dev/urandom of={mount_point}/data bs=1M count=100",
        shell=True,
        sudo=True,
        timeout=600,
    )
    cmd_result.assert_exit_code(
        message=f"Failed to write test data to {mount_point}/data."
    )

    # Capture md5sum.
    md5_result = node.execute(f"md5sum {mount_point}/data", shell=True, sudo=True)
    md5_result.assert_exit_code(message=f"md5sum failed on {mount_point}/data.")
    log.debug(f"Initial md5sum: {md5_result.stdout}")
    return md5_result.stdout


def _verify_data_integrity(
    node: Node,
    namespace: str,
    mount_point: str,
    expected_md5: str,
    log: Logger,
) -> None:
    """Remount and verify data integrity via md5sum comparison."""
    mount = node.tools[Mount]

    mount.mount(namespace, mount_point)

    md5_result = node.execute(f"md5sum {mount_point}/data", shell=True, sudo=True)
    md5_result.assert_exit_code(
        message=f"md5sum failed on {mount_point}/data after rebind."
    )
    log.debug(f"Post-rebind md5sum: {md5_result.stdout}")

    assert_that(md5_result.stdout).described_as(
        f"Data integrity check failed for {namespace}. "
        "md5sum changed after driver unbind/rebind cycle."
    ).is_equal_to(expected_md5)


def _verify_post_rebind_io(
    node: Node,
    mount_point: str,
    log: Logger,
) -> None:
    """Write and read back a small file to confirm I/O works after rebind."""
    sentinel = "NVMeRebindIOCheck"
    echo = node.tools[Echo]
    echo.write_to_file(
        sentinel,
        node.get_pure_path(f"{mount_point}/rebind_verify.txt"),
        sudo=True,
    )

    read_result = node.execute(
        f"cat {mount_point}/rebind_verify.txt",
        shell=True,
        sudo=True,
    )
    read_result.assert_exit_code(
        message="Failed to read back verification file after rebind."
    )
    assert_that(read_result.stdout.strip()).described_as(
        "Post-rebind I/O check failed: written and read data differ."
    ).is_equal_to(sentinel)
    log.debug("Post-rebind I/O verification succeeded.")


@TestSuiteMetadata(
    area="nvme",
    category="functional",
    name="NvmeUnbindRebind",
    description="""
    Validates NVMe driver unbind/rebind recovery on Linux.
    Ensures device rediscovery, data integrity, and continued
    I/O capability after a PCI remove-and-rescan cycle.
    """,
)
class NvmeUnbindRebindTestSuite(TestSuite):
    """Validate NVMe device recovery after PCI remove and rescan."""

    @TestCaseMetadata(
        description="""
        This test case validates that an NVMe device can survive a
        driver unbind/rebind cycle without data loss or functional
        degradation.

        Steps:
        1. Enumerate NVMe namespaces and record baseline device and
           error counts.
        2. Write known data to each NVMe namespace and capture the
           md5sum.
        3. Unmount all NVMe filesystems.
        4. Remove every NVMe PCI device (driver unbind) via sysfs.
        5. Trigger a PCI bus rescan (driver rebind).
        6. Verify that all NVMe devices are rediscovered.
        7. Remount each namespace and compare md5sum to confirm data
           integrity.
        8. Perform a post-rebind write/read to confirm I/O works.
        9. Compare NVMe error counts before and after the cycle.
        10. Check dmesg for kernel errors introduced by the cycle.
        """,
        priority=2,
        timeout=3600,
        requirement=simple_requirement(
            supported_features=[Nvme],
        ),
    )
    def verify_nvme_driver_unbind_rebind_recovery(
        self,
        node: Node,
        log: Logger,
    ) -> None:
        nvme = node.features[Nvme]
        lspci = node.tools[Lspci]
        nvme_cli = node.tools[Nvmecli]
        mount = node.tools[Mount]
        dmesg = node.tools[Dmesg]

        # --- Arrange ---

        # 1. Baseline: devices, namespaces, error counts, dmesg.
        namespaces = nvme.get_raw_nvme_disks()
        assert_that(len(namespaces)).described_as(
            "No NVMe namespaces found; at least one NVMe data disk required."
        ).is_greater_than(0)

        devices_before = lspci.get_device_names_by_type(
            DEVICE_TYPE_NVME, force_run=True
        )
        log.info(
            f"Baseline: {len(devices_before)} NVMe PCI device(s), "
            f"{len(namespaces)} namespace(s)."
        )

        error_counts_before: List[int] = [
            nvme_cli.get_error_count(ns) for ns in namespaces
        ]

        # Clear dmesg so post-rebind check only sees new messages.
        node.execute("dmesg --clear", shell=True, sudo=True)

        # 2. Write test data and capture md5sums.
        md5_map: dict[str, str] = {}
        mount_points: dict[str, str] = {}
        for namespace in namespaces:
            mount_point = namespace.rpartition("/")[-1]
            mount_points[namespace] = mount_point
            md5_map[namespace] = _write_test_data(node, namespace, mount_point, log)

        # 3. Sync and unmount before removing PCI devices.
        node.execute("sync", shell=True, sudo=True)
        for namespace in namespaces:
            mount.umount(namespace, mount_points[namespace], erase=False)
        log.info("All NVMe filesystems unmounted.")

        # --- Act ---

        # 4. Remove every NVMe PCI device (unbind).
        disabled_count = lspci.disable_devices_by_type(device_type=DEVICE_TYPE_NVME)
        log.info(f"Disabled {disabled_count} NVMe PCI device(s).")

        # 5. Rescan the PCI bus (rebind).
        lspci.enable_devices()
        log.info("PCI bus rescan completed.")

        # --- Assert ---

        # 6. All devices must be rediscovered.
        devices_after = lspci.get_device_names_by_type(DEVICE_TYPE_NVME, force_run=True)
        assert_that(devices_after).described_as(
            "Not all NVMe PCI devices reappeared after rescan. "
            f"Expected {len(devices_before)}, "
            f"found {len(devices_after)}."
        ).is_length(len(devices_before))

        namespaces_after = nvme.get_raw_nvme_disks()
        assert_that(namespaces_after).described_as(
            "Not all NVMe namespaces reappeared after rescan. "
            f"Expected {len(namespaces)}, "
            f"found {len(namespaces_after)}."
        ).is_length(len(namespaces))
        log.info(
            f"All {len(devices_after)} device(s) and "
            f"{len(namespaces_after)} namespace(s) recovered."
        )

        # 7. Data integrity check on every namespace.
        for namespace in namespaces:
            _verify_data_integrity(
                node,
                namespace,
                mount_points[namespace],
                md5_map[namespace],
                log,
            )

        # 8. Post-rebind I/O verification.
        for namespace in namespaces:
            _verify_post_rebind_io(node, mount_points[namespace], log)
        log.info("Data integrity and post-rebind I/O verified.")

        # 9. NVMe error count must not have increased.
        for i, namespace in enumerate(namespaces):
            error_count_after = nvme_cli.get_error_count(namespace)
            assert_that(error_counts_before[i]).described_as(
                f"NVMe error count increased for {namespace} after "
                "unbind/rebind cycle "
                f"(before={error_counts_before[i]}, "
                f"after={error_count_after})."
            ).is_equal_to(error_count_after)

        # 10. No kernel errors in dmesg during the cycle.
        dmesg.check_kernel_errors(force_run=True, throw_error=True)
        log.info("NVMe driver unbind/rebind recovery validated successfully.")

    def after_case(self, log: Logger, **kwargs: Any) -> None:
        """Clean up mounts created during the test."""
        node: Node = kwargs["node"]
        mount = node.tools[Mount]
        try:
            nvme = node.features[Nvme]
            namespaces = nvme.get_raw_nvme_disks()
            for namespace in namespaces:
                mount_point = namespace.rpartition("/")[-1]
                mount.umount(
                    disk_name=namespace,
                    point=mount_point,
                )
        except Exception:
            log.debug(
                "Non-critical: cleanup of NVMe mount points encountered an error."
            )
