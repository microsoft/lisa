# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
import uuid
from pathlib import PurePosixPath
from typing import Any, Dict, List, Tuple, cast
from xml.etree import ElementTree

from lisa import (
    Environment,
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.messages import DiskSetupType, DiskType
from lisa.microsoft.testsuites.performance.common import perf_disk
from lisa.operating_system import Windows
from lisa.sut_orchestrator import CLOUD_HYPERVISOR
from lisa.sut_orchestrator.util.schema import HostDevicePoolType
from lisa.testsuite import TestResult
from lisa.tools import Cat, FileSystem, Kill, Ls, Lsblk, Lscpu, Lspci, Mkfs, Mount, Rm
from lisa.tools.lsblk import DiskInfo, PartitionInfo
from lisa.tools.swap import Swap
from lisa.util import LisaException
from lisa.util.constants import DEVICE_TYPE_NVME

_PCI_BDF_PATTERN = re.compile(
    r"^(?P<domain>[0-9a-fA-F]{4}):(?P<bus>[0-9a-fA-F]{2}):"
    r"(?P<slot>[0-9a-fA-F]{2})\.(?P<function>[0-9a-fA-F])$"
)
_NVME_CONTROLLER_PATTERN = re.compile(r"^nvme\d+$")
_NVME_NAMESPACE_PATTERN = re.compile(r"^nvme\d+n\d+$")
_PASSTHROUGH_NVME_MOUNT_PREFIX = "/mnt/passthrough_nvme"
_UNSAFE_BLOCK_TYPES = {"crypt", "dm", "lvm", "md", "mpath", "raid"}
_MAX_FIO_CASES = 4
_MAX_FIO_IODEPTH = 64
_MAX_FIO_RUNTIME_SECONDS = 300
_MAX_FIO_SIZE_MB = 4096
_MAX_FIO_BLOCK_SIZE_KB = 1024


def _normalize_pci_bdf(pci_bdf: str) -> str:
    match = _PCI_BDF_PATTERN.fullmatch(pci_bdf.strip())
    if not match:
        raise LisaException(f"Invalid PCI BDF '{pci_bdf}'")
    return (
        f"{match.group('domain').lower()}:"
        f"{match.group('bus').lower()}:"
        f"{match.group('slot').lower()}."
        f"{match.group('function').lower()}"
    )


def _address_element_to_bdf(address: ElementTree.Element) -> str:
    try:
        domain = int(address.attrib.get("domain", "0"), 0)
        bus = int(address.attrib["bus"], 0)
        slot = int(address.attrib["slot"], 0)
        function = int(address.attrib["function"], 0)
    except (KeyError, ValueError) as error:
        raise LisaException(
            f"Invalid PCI address in libvirt domain XML: {address.attrib}"
        ) from error
    return f"{domain:04x}:{bus:02x}:{slot:02x}.{function:x}"


def _get_guest_pci_bdf_from_domain_xml(domain_xml: str, host_pci_bdf: str) -> str:
    try:
        domain = ElementTree.fromstring(domain_xml)
    except ElementTree.ParseError as error:
        raise LisaException("Cannot parse libvirt domain XML") from error

    normalized_host_bdf = _normalize_pci_bdf(host_pci_bdf)
    guest_bdfs: List[str] = []
    for host_device in domain.findall("./devices/hostdev"):
        if host_device.attrib.get("type") != "pci":
            continue
        source_address = host_device.find("./source/address")
        if source_address is None:
            continue
        if _address_element_to_bdf(source_address) != normalized_host_bdf:
            continue

        guest_address = host_device.find("./address")
        if guest_address is None:
            raise LisaException(
                f"Libvirt host device '{normalized_host_bdf}' does not expose a "
                "guest PCI address"
            )
        guest_bdfs.append(_address_element_to_bdf(guest_address))

    if len(guest_bdfs) != 1:
        raise LisaException(
            f"Expected exactly one guest PCI address for assigned host device "
            f"'{normalized_host_bdf}', found {len(guest_bdfs)}: {guest_bdfs}"
        )
    return guest_bdfs[0]


def _get_descendants(partitions: List[PartitionInfo]) -> List[PartitionInfo]:
    descendants: List[PartitionInfo] = []
    for partition in partitions:
        descendants.append(partition)
        descendants.extend(_get_descendants(partition.logical_devices))
    return descendants


def _get_disk_safety_issues(
    disk: DiskInfo,
    swap_devices: List[str],
    holders: List[str],
) -> List[str]:
    issues: List[str] = []
    descendants = _get_descendants(disk.partitions)
    mountpoints = [disk.mountpoint] + [item.mountpoint for item in descendants]
    device_paths = {disk.device_name}
    device_paths.update(item.device_name for item in descendants)

    if any(
        mountpoint == "/" or mountpoint.startswith("/boot")
        for mountpoint in mountpoints
        if mountpoint
    ):
        issues.append("backs the root or boot filesystem")
    elif any(mountpoints):
        issues.append("is mounted or has mounted child devices")

    matching_swap_devices = sorted(set(swap_devices).intersection(device_paths))
    if (
        matching_swap_devices
        or disk.fstype == "swap"
        or any(item.fstype == "swap" for item in descendants)
    ):
        issues.append(
            "is used for swap"
            + (f": {matching_swap_devices}" if matching_swap_devices else "")
        )

    logical_types = sorted(
        {item.type for item in descendants if item.type in _UNSAFE_BLOCK_TYPES}
    )
    if logical_types:
        issues.append(f"has unsafe logical block relationships: {logical_types}")

    if holders:
        issues.append(f"has active block holders: {sorted(holders)}")

    return issues


@TestSuiteMetadata(
    area="storage passthrough",
    category="performance",
    description=(
        "Validates visibility and bounded FIO operation on an NVMe namespace "
        "assigned to a Cloud Hypervisor guest through PCI passthrough."
    ),
    owner="v-aratakonda",
    requirement=simple_requirement(
        supported_platform_type=[CLOUD_HYPERVISOR],
        unsupported_os=[Windows],
    ),
)
class StoragePassthroughPerfTests(TestSuite):
    """Validate an exactly identified NVMe passthrough namespace."""

    TIME_OUT = 12000

    @TestCaseMetadata(
        description=(
            "Verify that the assigned host NVMe controller maps to exactly one "
            "guest PCI controller and namespace.\n"
            "This test is generated by the lisa_test_writer prompt."
        ),
        priority=4,
        timeout=1800,
        requirement=simple_requirement(
            supported_platform_type=[CLOUD_HYPERVISOR],
        ),
        tags=["ai-generated"],
    )
    def verify_storage_passthrough_nvme_visible(
        self,
        log: Logger,
        node: Node,
        environment: Environment,
        result: TestResult,
    ) -> None:
        host_bdf, guest_bdf, namespace = self._resolve_passthrough_nvme_namespace(
            node, environment, log
        )
        result.message = (
            f"Resolved passthrough NVMe host={host_bdf}, guest={guest_bdf}, "
            f"namespace={namespace}"
        )

    @TestCaseMetadata(
        description=(
            "Run bounded random-read FIO only after the assigned passthrough "
            "NVMe namespace is uniquely resolved and proven unused."
        ),
        priority=3,
        timeout=TIME_OUT,
        requirement=simple_requirement(
            supported_platform_type=[CLOUD_HYPERVISOR],
        ),
        tags=["ai-generated"],
    )
    def perf_storage_passthrough_fio_randread(
        self,
        log: Logger,
        node: Node,
        environment: Environment,
        result: TestResult,
        variables: Dict[str, Any],
    ) -> None:
        self._run_storage_passthrough_fio(
            log, node, environment, result, variables, "randread"
        )

    @TestCaseMetadata(
        description=(
            "Run bounded random-write FIO only after the assigned passthrough "
            "NVMe namespace is uniquely resolved and proven unused."
        ),
        priority=3,
        timeout=TIME_OUT,
        requirement=simple_requirement(
            supported_platform_type=[CLOUD_HYPERVISOR],
        ),
        tags=["ai-generated"],
    )
    def perf_storage_passthrough_fio_randwrite(
        self,
        log: Logger,
        node: Node,
        environment: Environment,
        result: TestResult,
        variables: Dict[str, Any],
    ) -> None:
        self._run_storage_passthrough_fio(
            log, node, environment, result, variables, "randwrite"
        )

    def _run_storage_passthrough_fio(
        self,
        log: Logger,
        node: Node,
        environment: Environment,
        result: TestResult,
        variables: Dict[str, Any],
        fio_mode: str,
    ) -> None:
        host_bdf, guest_bdf, namespace = self._resolve_passthrough_nvme_namespace(
            node, environment, log
        )
        self._validate_namespace_is_safe(node, namespace)
        testcases = _get_fio_testcases(variables)

        log.info(
            f"Selected passthrough NVMe namespace '{namespace}' from host "
            f"'{host_bdf}' at guest PCI address '{guest_bdf}'"
        )
        node.mark_dirty()
        mount_point = f"{_PASSTHROUGH_NVME_MOUNT_PREFIX}_{uuid.uuid4().hex}"
        node.shell.mkdir(PurePosixPath(mount_point), exist_ok=True)
        mounted = False
        fio_files: List[str] = []
        try:
            self._validate_namespace_is_safe(node, namespace)
            node.tools[Mkfs].format_disk(namespace, FileSystem.ext4)
            node.tools[Mount].mount(namespace, mount_point, options="nobarrier")
            mounted = True

            thread_count = node.tools[Lscpu].get_thread_count()
            for testcase in testcases:
                start_iodepth = int(testcase.get("start_iodepth", 1))
                max_iodepth = int(testcase.get("max_iodepth", 4))
                block_size = int(testcase.get("block_size", 4))
                runtime = int(testcase.get("time", 60))
                size_mb = int(testcase.get("size_mb", 512))
                overwrite = bool(testcase.get("overwrite", False))
                num_jobs = _get_num_jobs(start_iodepth, max_iodepth, thread_count)
                filename = f"passthrough_nvme_fio_{uuid.uuid4()}"
                fio_files.append(f"{mount_point}/{filename}")
                test_name = f"passthrough_nvme_{fio_mode}_{size_mb}_MB_{block_size}K"
                log.info(f"Running bounded FIO testcase '{test_name}'")
                perf_disk(
                    node=node,
                    start_iodepth=start_iodepth,
                    max_iodepth=max_iodepth,
                    filename=filename,
                    test_result=result,
                    test_name=test_name,
                    num_jobs=num_jobs,
                    block_size=block_size,
                    time=runtime,
                    size_mb=size_mb,
                    overwrite=overwrite,
                    core_count=thread_count,
                    disk_count=1,
                    disk_setup_type=DiskSetupType.raw,
                    disk_type=DiskType.nvme,
                    cwd=PurePosixPath(mount_point),
                    fio_modes=[fio_mode],
                )
        finally:
            try:
                node.tools[Kill].by_name("fio", ignore_not_exist=True)
            finally:
                if mounted:
                    try:
                        for fio_file in fio_files:
                            node.tools[Rm].remove_file(fio_file, sudo=True)
                    finally:
                        node.tools[Mount].umount(namespace, mount_point, erase=False)
                node.tools[Rm].remove_directory(mount_point, sudo=True)

    def _resolve_passthrough_nvme_namespace(
        self,
        node: Node,
        environment: Environment,
        log: Logger,
    ) -> Tuple[str, str, str]:
        from lisa.sut_orchestrator.libvirt.context import get_node_context

        node_context = get_node_context(node)
        nvme_contexts = [
            context
            for context in node_context.passthrough_devices
            if context.pool_type == HostDevicePoolType.PCI_NVME
        ]
        assigned_devices = [
            device for context in nvme_contexts for device in context.device_list
        ]
        requested_count = sum(context.requested_count for context in nvme_contexts)
        if requested_count != 1:
            raise LisaException(
                "Storage passthrough tests require exactly one requested "
                f"PCI_NVME device; requested={requested_count}"
            )

        platform = environment.platform
        host_node = getattr(platform, "host_node", None) if platform else None
        if host_node is None:
            raise LisaException("No libvirt host node is available")
        host_nvme_bdfs = {
            _normalize_pci_bdf(device.slot)
            for device in cast(Node, host_node)
            .tools[Lspci]
            .get_devices_by_type(DEVICE_TYPE_NVME, force_run=True)
        }
        assigned_bdfs = [
            self._device_address_to_bdf(device) for device in assigned_devices
        ]
        assigned_nvme_bdfs = [
            pci_bdf for pci_bdf in assigned_bdfs if pci_bdf in host_nvme_bdfs
        ]
        if len(assigned_nvme_bdfs) != 1:
            raise LisaException(
                "Storage passthrough tests require exactly one assigned PCI_NVME "
                f"device matching host inventory; assigned={assigned_bdfs}, "
                f"host NVMe devices={sorted(host_nvme_bdfs)}"
            )

        host_bdf = assigned_nvme_bdfs[0]
        domain = cast(Any, node_context.domain)
        if domain is None:
            raise LisaException("No libvirt domain is available for the guest node")
        try:
            domain_xml = cast(str, domain.XMLDesc(0))
        except Exception as error:
            raise LisaException("Failed to read live libvirt domain XML") from error
        guest_bdf = _get_guest_pci_bdf_from_domain_xml(domain_xml, host_bdf)

        host_ids = self._get_pci_ids(cast(Node, host_node), host_bdf)
        guest_device = self._get_guest_nvme_device(node, guest_bdf)
        guest_ids = (guest_device.vendor_id.lower(), guest_device.device_id.lower())
        if guest_ids != host_ids:
            raise LisaException(
                f"Resolved guest NVMe '{guest_bdf}' has vendor/device "
                f"{guest_ids[0]}:{guest_ids[1]}, expected "
                f"{host_ids[0]}:{host_ids[1]} from host '{host_bdf}'"
            )

        namespace = self._get_namespace_for_guest_bdf(node, guest_bdf)
        log.info(
            f"Mapped assigned NVMe host '{host_bdf}' to guest '{guest_bdf}' "
            f"and namespace '{namespace}'"
        )
        return host_bdf, guest_bdf, namespace

    @staticmethod
    def _device_address_to_bdf(device: Any) -> str:
        try:
            return (
                f"{int(device.domain or '0', 16):04x}:"
                f"{int(device.bus, 16):02x}:"
                f"{int(device.slot, 16):02x}."
                f"{int(device.function, 16):x}"
            )
        except (AttributeError, TypeError, ValueError) as error:
            raise LisaException(
                f"Invalid assigned PCI_NVME device address: {device}"
            ) from error

    @staticmethod
    def _get_pci_ids(node: Node, pci_bdf: str) -> Tuple[str, str]:
        cat = node.tools[Cat]
        sysfs_path = f"/sys/bus/pci/devices/{pci_bdf}"
        vendor_id = cat.read(f"{sysfs_path}/vendor", sudo=True).strip()
        device_id = cat.read(f"{sysfs_path}/device", sudo=True).strip()
        return (
            vendor_id.lower().replace("0x", "").zfill(4),
            device_id.lower().replace("0x", "").zfill(4),
        )

    @staticmethod
    def _get_guest_nvme_device(node: Node, guest_bdf: str) -> Any:
        devices = node.tools[Lspci].get_devices_by_type(
            DEVICE_TYPE_NVME, force_run=True
        )
        matches = [
            device for device in devices if _normalize_pci_bdf(device.slot) == guest_bdf
        ]
        if len(matches) != 1:
            raise LisaException(
                f"Expected exactly one NVMe controller at guest PCI address "
                f"'{guest_bdf}', found {len(matches)}"
            )
        return matches[0]

    @staticmethod
    def _get_namespace_for_guest_bdf(node: Node, guest_bdf: str) -> str:
        ls = node.tools[Ls]
        controller_entries = ls.list(
            f"/sys/bus/pci/devices/{guest_bdf}/nvme", sudo=True
        )
        controllers = sorted(
            {
                PurePosixPath(path.rstrip("/")).name
                for path in controller_entries
                if _NVME_CONTROLLER_PATTERN.fullmatch(
                    PurePosixPath(path.rstrip("/")).name
                )
            }
        )
        if len(controllers) != 1:
            raise LisaException(
                f"Expected exactly one NVMe controller under guest PCI address "
                f"'{guest_bdf}', found {len(controllers)}: {controllers}"
            )

        controller = controllers[0]
        namespace_entries = ls.list(f"/sys/class/nvme/{controller}", sudo=True)
        namespaces = sorted(
            {
                PurePosixPath(path.rstrip("/")).name
                for path in namespace_entries
                if _NVME_NAMESPACE_PATTERN.fullmatch(
                    PurePosixPath(path.rstrip("/")).name
                )
            }
        )
        if len(namespaces) != 1:
            raise LisaException(
                f"Expected exactly one namespace for guest NVMe controller "
                f"'{controller}', found {len(namespaces)}: {namespaces}"
            )

        namespace = f"/dev/{namespaces[0]}"
        if not ls.path_exists(namespace, sudo=True):
            raise LisaException(
                f"Resolved passthrough NVMe namespace '{namespace}' does not exist"
            )
        return namespace

    @staticmethod
    def _validate_namespace_is_safe(node: Node, namespace: str) -> None:
        namespace_name = PurePosixPath(namespace).name
        if not _NVME_NAMESPACE_PATTERN.fullmatch(namespace_name):
            raise LisaException(f"Invalid NVMe namespace path '{namespace}'")
        disks = node.tools[Lsblk].get_disks(force_run=True)
        matching_disks = [disk for disk in disks if disk.name == namespace_name]
        if len(matching_disks) != 1:
            raise LisaException(
                f"Expected exactly one block disk for namespace '{namespace}', "
                f"found {len(matching_disks)}"
            )
        disk = matching_disks[0]
        descendants = _get_descendants(disk.partitions)
        block_names = [disk.name] + [item.name for item in descendants]
        holders: List[str] = []
        ls = node.tools[Ls]
        for block_name in block_names:
            holders.extend(ls.list(f"/sys/class/block/{block_name}/holders", sudo=True))
        swap_devices = [
            swap.partition for swap in node.tools[Swap].get_swap_partitions()
        ]
        issues = _get_disk_safety_issues(disk, swap_devices, holders)
        if issues:
            raise LisaException(
                f"Refusing destructive FIO on '{namespace}': " + "; ".join(issues)
            )


def _get_fio_testcases(variables: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw_testcases = variables.get("fio_testcase_list")
    if raw_testcases is None:
        testcases: List[Dict[str, Any]] = [
            {
                "start_iodepth": 1,
                "max_iodepth": 4,
                "block_size": 4,
                "size_mb": 512,
                "time": 60,
            }
        ]
    elif isinstance(raw_testcases, list) and all(
        isinstance(testcase, dict) for testcase in raw_testcases
    ):
        testcases = cast(List[Dict[str, Any]], raw_testcases)
    else:
        raise LisaException("fio_testcase_list must be a list of mappings")

    if not testcases or len(testcases) > _MAX_FIO_CASES:
        raise LisaException(
            f"fio_testcase_list must contain between 1 and {_MAX_FIO_CASES} cases"
        )
    for testcase in testcases:
        start_iodepth = int(testcase.get("start_iodepth", 1))
        max_iodepth = int(testcase.get("max_iodepth", 4))
        block_size = int(testcase.get("block_size", 4))
        runtime = int(testcase.get("time", 60))
        size_mb = int(testcase.get("size_mb", 512))
        if not 1 <= start_iodepth <= max_iodepth <= _MAX_FIO_IODEPTH:
            raise LisaException(
                f"FIO iodepth must satisfy 1 <= start <= max <= "
                f"{_MAX_FIO_IODEPTH}: {testcase}"
            )
        if not 1 <= runtime <= _MAX_FIO_RUNTIME_SECONDS:
            raise LisaException(
                f"FIO runtime must be between 1 and "
                f"{_MAX_FIO_RUNTIME_SECONDS} seconds: {testcase}"
            )
        if not 1 <= size_mb <= _MAX_FIO_SIZE_MB:
            raise LisaException(
                f"FIO size_mb must be between 1 and {_MAX_FIO_SIZE_MB}: {testcase}"
            )
        if not 1 <= block_size <= _MAX_FIO_BLOCK_SIZE_KB:
            raise LisaException(
                f"FIO block_size must be between 1 and "
                f"{_MAX_FIO_BLOCK_SIZE_KB} KiB: {testcase}"
            )
    return testcases


def _get_num_jobs(start_iodepth: int, max_iodepth: int, thread_count: int) -> List[int]:
    if start_iodepth < 1 or start_iodepth > max_iodepth or thread_count < 1:
        raise LisaException(
            f"Invalid FIO job parameters: start_iodepth={start_iodepth}, "
            f"max_iodepth={max_iodepth}, thread_count={thread_count}"
        )
    num_jobs: List[int] = []
    iodepth = start_iodepth
    while iodepth <= max_iodepth:
        num_jobs.append(min(iodepth, thread_count))
        iodepth *= 2
    return num_jobs
