# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, Tuple, cast

from assertpy import assert_that
from microsoft.testsuites.network.common import (
    cleanup_iperf3,
    disable_enable_devices,
    initialize_nic_info,
    reload_modules,
    remove_extra_nics,
    restore_extra_nics,
    skip_if_pci_only_nics,
    sriov_basic_test,
    sriov_disable_enable,
    sriov_vf_connection_test,
)

from lisa import (
    Environment,
    Logger,
    Node,
    RemoteNode,
    SkippedException,
    TcpConnectionException,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    constants,
    features,
    node_requirement,
    schema,
    search_space,
    simple_requirement,
)
from lisa.base_tools import Systemctl
from lisa.features import NetworkInterface, SerialConsole, StartStop
from lisa.nic import NicInfo
from lisa.operating_system import BSD, Posix, Windows
from lisa.sut_orchestrator import AZURE, HYPERV
from lisa.tools import (
    Cat,
    Dmesg,
    Ethtool,
    FileSystem,
    Firewall,
    InterruptInspector,
    Iperf3,
    Journalctl,
    Kill,
    Ls,
    Lscpu,
    Lspci,
    Mount,
    Readlink,
    Service,
)
from lisa.util import (
    LisaException,
    LisaTimeoutException,
    UnsupportedDistroException,
    check_till_timeout,
)
from lisa.util.shell import wait_tcp_port_ready


@TestSuiteMetadata(
    area="sriov",
    category="functional",
    description="""
    This test suite uses to verify accelerated network functionality.
    """,
)
class Sriov(TestSuite):
    TIME_OUT = 300
    DEBUGFS_PATH = "/sys/kernel/debug"
    # Reads are capped so a driver whose debugfs file streams without end
    # cannot hang the run. The cap sits far above the largest dump file seen
    # from any driver, so it bounds runaway reads without truncating real ones.
    DEBUGFS_READ_CAP_BYTES = 1048576
    # A single debugfs read that blocks is abandoned after this long, which
    # bounds a whole tree walk even when many files misbehave.
    DEBUGFS_READ_TIMEOUT_SECONDS = 5
    # `timeout` reports 124 when it has to signal the child, and 137 when that
    # signal had to be escalated to KILL. Either way the read never answered.
    DEBUGFS_READ_TIMEOUT_EXIT_CODES = (-124, -137)
    # Failed to rename network interface 3 from 'eth1' to 'enP45159s1': Device or resource busy # noqa: E501
    _device_rename_pattern = re.compile(
        r"Failed to rename network interface .* from '.*' "
        "to '.*': Device or resource busy",
        re.M,
    )

    def before_case(self, log: Logger, **kwargs: Any) -> None:
        environment: Environment = kwargs.pop("environment")
        for node in environment.nodes.list():
            node.tools[Firewall].stop()
            node.features[NetworkInterface].switch_sriov(
                enable=True, wait=True, reset_connections=True
            )

    @TestCaseMetadata(
        description="""
        This case verifies all services state with Sriov enabled.

        Steps,
        1. Get overrall state from `systemctl status`, if no systemctl command,
           skip the testing
        2. The expected state should be `running`
        """,
        priority=1,
        requirement=simple_requirement(
            network_interface=features.Sriov(),
        ),
    )
    def verify_services_state(self, node: Node) -> None:
        try:
            check_till_timeout(
                lambda: node.tools[Systemctl].state() == "running",
                timeout_message="wait for systemctl status to be running",
            )
        except LisaTimeoutException:
            udevd_status = node.tools[Journalctl].logs_for_unit("systemd-udevd")
            matched = self._device_rename_pattern.search(udevd_status)
            if matched:
                raise LisaException(
                    f"{matched[0]}. "
                    "There is a race condition when rename VF nics, "
                    "it causes boot delay, it should be fixed in "
                    "systemd - 245.4-4ubuntu3.21"
                )
        except UnsupportedDistroException as e:
            raise SkippedException(e) from e

    @TestCaseMetadata(
        description="""
        This case verifies module of sriov network interface is loaded and each
         synthetic nic is paired with one VF.

        Steps,
        1. Check VF of synthetic nic is paired.
        2. Check module of sriov network device is loaded.
        3. Check VF counts listed from lspci is expected.
        """,
        priority=1,
        requirement=simple_requirement(
            min_count=2,
            network_interface=features.Sriov(),
        ),
    )
    def verify_sriov_basic(self, environment: Environment) -> None:
        initialize_nic_info(environment)
        sriov_basic_test(environment)

    @TestCaseMetadata(
        description="""
        This case verifies module of sriov network interface is loaded and
         each synthetic nic is paired with one VF, and check rx statistics of source
         and tx statistics of dest increase after send 200 Mb file from source to dest.

        Steps,
        1. Check VF of synthetic nic is paired.
        2. Check module of sriov network device is loaded.
        3. Check VF counts listed from lspci is expected.
        4. Setup SSH connection between source and dest with key authentication.
        5. Ping the dest IP from the source machine to check connectivity.
        6. Generate 200Mb file, copy from source to dest.
        7. Check rx statistics of source VF and tx statistics of dest VF is increased.
        """,
        priority=1,
        requirement=simple_requirement(
            min_count=2,
            network_interface=features.Sriov(),
        ),
    )
    def verify_sriov_single_vf_connection(self, environment: Environment) -> None:
        vm_nics = initialize_nic_info(environment)
        sriov_basic_test(environment)
        sriov_vf_connection_test(environment, vm_nics)

    @TestCaseMetadata(
        description="""
        This case needs 2 nodes and 64 Vcpus. And it verifies module of sriov network
         interface is loaded and each synthetic nic is paired with one VF, and check
         rx statistics of source and tx statistics of dest increase after send 200 Mb
         file from source to dest.

        Steps,
        1. Check VF of synthetic nic is paired.
        2. Check module of sriov network device is loaded.
        3. Check VF counts listed from lspci is expected.
        4. Setup SSH connection between source and dest with key authentication.
        5. Ping the dest IP from the source machine to check connectivity.
        6. Generate 200Mb file, copy from source to dest.
        7. Check rx statistics of source VF and tx statistics of dest VF is increased.
        """,
        priority=2,
        requirement=simple_requirement(
            min_count=2,
            min_core_count=64,
            network_interface=features.Sriov(),
        ),
    )
    def verify_sriov_single_vf_connection_max_cpu(
        self, environment: Environment
    ) -> None:
        vm_nics = initialize_nic_info(environment)
        sriov_basic_test(environment)
        sriov_vf_connection_test(environment, vm_nics)

    @TestCaseMetadata(
        description="""
        This case needs 2 nodes and max nics. And it verifies module of sriov network
         interface is loaded and each synthetic nic is paired with one VF, and check
         rx statistics of source and tx statistics of dest increase after send 200 Mb
         file from source to dest.

        Steps,
        1. Check VF of synthetic nic is paired.
        2. Check module of sriov network device is loaded.
        3. Check VF counts listed from lspci is expected.
        4. Setup SSH connection between source and dest with key authentication.
        5. Ping the dest IP from the source machine to check connectivity.
        6. Generate 200Mb file, copy from source to dest.
        7. Check rx statistics of source VF and tx statistics of dest VF is increased.
        """,
        priority=2,
        requirement=simple_requirement(
            min_count=2,
            network_interface=schema.NetworkInterfaceOptionSettings(
                data_path=schema.NetworkDataPath.Sriov,
                nic_count=search_space.IntRange(min=2, choose_max_value=True),
            ),
        ),
    )
    def verify_sriov_max_vf_connection(self, environment: Environment) -> None:
        vm_nics = initialize_nic_info(environment)
        sriov_basic_test(environment)
        sriov_vf_connection_test(environment, vm_nics)

    @TestCaseMetadata(
        description="""
        This case needs 2 nodes, max nics and 64 Vcpus. And it verifies module of sriov
         network interface is loaded and each synthetic nic is paired with one VF, and
         check rx statistics of source and tx statistics of dest increase after send 200
         Mb file from source to dest.

        Steps,
        1. Check VF of synthetic nic is paired.
        2. Check module of sriov network device is loaded.
        3. Check VF counts listed from lspci is expected.
        4. Setup SSH connection between source and dest with key authentication.
        5. Ping the dest IP from the source machine to check connectivity.
        6. Generate 200Mb file, copy from source to dest.
        7. Check rx statistics of source VF and tx statistics of dest VF is increased.
        """,
        priority=2,
        requirement=simple_requirement(
            min_count=2,
            min_core_count=64,
            network_interface=schema.NetworkInterfaceOptionSettings(
                data_path=schema.NetworkDataPath.Sriov,
                nic_count=search_space.IntRange(min=2, choose_max_value=True),
            ),
        ),
    )
    def verify_sriov_max_vf_connection_max_cpu(self, environment: Environment) -> None:
        vm_nics = initialize_nic_info(environment)
        sriov_basic_test(environment)
        sriov_vf_connection_test(environment, vm_nics)

    @TestCaseMetadata(
        description="""
        This case verify VM works well after disable and enable accelerated network in
        network interface through sdk.

        Steps,
        1. Do the basic sriov check.
        2. Set enable_accelerated_networking as False to disable sriov.
        3. Set enable_accelerated_networking as True to enable sriov.
        4. Do the basic sriov check.
        5. Do step 2 ~ step 4 for 2 times.
        """,
        priority=1,
        requirement=simple_requirement(
            network_interface=features.Sriov(),
            supported_platform_type=[AZURE, HYPERV],
        ),
    )
    def verify_sriov_disable_enable(self, environment: Environment) -> None:
        skip_if_pci_only_nics(environment)

        sriov_disable_enable(environment)

    @TestCaseMetadata(
        description="""
        This case verify VM works well after disable and enable PCI device inside VM.

        Steps,
        1. Disable sriov PCI device inside the VM.
        2. Enable sriov PCI device inside the VM.
        3. Do the basic sriov check.
        4. Do VF connection test.
        """,
        priority=2,
        requirement=simple_requirement(
            min_count=2,
            network_interface=features.Sriov(),
        ),
    )
    def verify_sriov_disable_enable_pci(self, environment: Environment) -> None:
        skip_if_pci_only_nics(environment)

        disable_enable_devices(environment)
        vm_nics = initialize_nic_info(environment)
        sriov_basic_test(environment)
        sriov_vf_connection_test(environment, vm_nics)

    @TestCaseMetadata(
        description="""
        This case verify VM works well after down the VF nic and up VF nic inside VM.

        Steps,
        1. Do the basic sriov check.
        2. Do network connection test with bring down the VF nic.
        3. After copy 200Mb file from source to desc.
        4. Check rx statistics of source synthetic nic and tx statistics of dest
         synthetic nic is increased.
        5. Bring up VF nic.
        """,
        priority=2,
        requirement=simple_requirement(
            min_count=2,
            network_interface=features.Sriov(),
        ),
    )
    def verify_sriov_disable_enable_on_guest(self, environment: Environment) -> None:
        skip_if_pci_only_nics(environment)

        vm_nics = initialize_nic_info(environment)
        sriov_basic_test(environment)
        sriov_vf_connection_test(environment, vm_nics, turn_off_lower=True)

    @TestCaseMetadata(
        description="""
        This case verifies that whatever the SR-IOV VF driver exposes in
        debugfs can actually be read back. debugfs is the primary first-look
        diagnostic when a VF misbehaves in production, so a file that is
        published there and then refuses to answer is a defect in the driver
        regardless of what it was meant to report.

        Steps,
        1. Ensure debugfs is mounted at /sys/kernel/debug.
        2. Identify the SR-IOV VF and resolve its bound driver from sysfs.
         If no driver is bound, fail when the kernel logged a probe failure
         against the VF, since a driver was present and refused it and the
         VM has lost accelerated networking, and skip when it logged none,
         since no driver in this kernel claims the VF at all.
        3. Locate the driver's debugfs directory. Skip if it exposes none,
         since the driver then implements no debugfs diagnostics at all.
        4. Read every readable regular file in that tree, with each read
         bounded by a byte cap and a timeout. Write-only nodes, such as
         command-staging interfaces, are not read.
        5. Skip if the tree holds no readable file, or if every file in it
         comes back empty. Both mean the driver published nothing to check,
         which is a property of the driver rather than a fault.
        6. Assert that no read hung. A read that returns an error is logged
         rather than asserted on, since some entries are command interfaces
         that answer only once a command has been staged through them, and
         since a kernel in lockdown refuses any debugfs file that is not
         read-only. A read that never answers has no such innocent
         explanation and blocks whoever is diagnosing the VF.

        This test is generated by the lisa_test_writer prompt.
        """,
        priority=2,
        requirement=simple_requirement(
            network_interface=features.Sriov(),
            # debugfs is a Linux kernel filesystem, so there is nothing for
            # this case to inspect on any other OS.
            unsupported_os=[BSD, Windows],
        ),
        tags=["ai-generated"],
    )
    def verify_sriov_debugfs_diagnostics(self, node: Node, log: Logger) -> None:
        mount = node.tools[Mount]
        if not mount.check_mount_point_exist(self.DEBUGFS_PATH):
            log.info("mounting debugfs for SR-IOV diagnostics")
            try:
                mount.mount(
                    name="debugfs",
                    point=self.DEBUGFS_PATH,
                    fs_type=FileSystem.debugfs,
                )
            except AssertionError as error:
                raise SkippedException(
                    f"unable to mount debugfs at {self.DEBUGFS_PATH}: {error}. "
                    "Verify the kernel is built with CONFIG_DEBUG_FS."
                ) from error
            if not mount.check_mount_point_exist(self.DEBUGFS_PATH):
                raise SkippedException(
                    f"debugfs is not mounted at {self.DEBUGFS_PATH} after "
                    "mount attempt. Verify the kernel is built with "
                    "CONFIG_DEBUG_FS."
                )

        vf_slots = node.tools[Lspci].get_device_names_by_type(
            constants.DEVICE_TYPE_SRIOV, force_run=True
        )
        assert_that(vf_slots).described_as(
            "an SR-IOV VF PCI device must be present to inspect its debugfs "
            "diagnostics"
        ).is_not_empty()
        vf_slot = vf_slots[0]

        # A logged probe failure means a driver refused the VF and the VM has
        # lost accelerated networking. Silence means no driver ever claimed
        # it, so this kernel predates the VF.
        ls = node.tools[Ls]
        driver_link = f"/sys/bus/pci/devices/{vf_slot}/driver"
        if not ls.path_exists(driver_link, sudo=True):
            modalias = node.tools[Cat].read(
                f"/sys/bus/pci/devices/{vf_slot}/modalias",
                sudo=True,
                force_run=True,
            )
            probe_failures = [
                line
                for line in node.tools[Dmesg].get_output(force_run=True).splitlines()
                if vf_slot in line and "probe of" in line and "failed" in line
            ]
            if not probe_failures:
                raise SkippedException(
                    f"SR-IOV VF {vf_slot} (modalias {modalias}) has no driver "
                    "bound to it and the kernel logged no probe failure "
                    "against it, so no driver in this kernel claims the VF "
                    "and the distro predates it."
                )
            raise LisaException(
                f"SR-IOV VF {vf_slot} (modalias {modalias}) has no driver "
                "bound to it because its driver probe failed, so the VM has "
                f"lost accelerated networking: {probe_failures[-1]}"
            )

        driver_path = node.tools[Readlink].get_canonical_path(driver_link)
        driver_name = PurePosixPath(driver_path).name

        # The driver's debugfs tree is always rooted directly under
        # /sys/kernel/debug/<name>. Some drivers register under a shortened
        # module name that drops a trailing component naming the sub-driver,
        # so every prefix of the module name is tried, longest first, rather
        # than a fixed list of suffixes that only covers known drivers.
        parts = driver_name.split("_")
        candidates = ["_".join(parts[:count]) for count in range(len(parts), 0, -1)]

        debugfs_root = next(
            (
                f"{self.DEBUGFS_PATH}/{candidate}"
                for candidate in candidates
                if ls.path_exists(f"{self.DEBUGFS_PATH}/{candidate}", sudo=True)
            ),
            "",
        )
        if not debugfs_root:
            raise SkippedException(
                f"driver {driver_name} of SR-IOV VF {vf_slot} exposes no "
                f"debugfs directory under {self.DEBUGFS_PATH}. This driver "
                "does not implement debugfs diagnostics."
            )
        log.info(f"inspecting debugfs tree {debugfs_root} of VF {vf_slot}")

        # `timeout` reports 124 when it has to signal the child, and 137 when
        # that signal had to be escalated to KILL. Either way the read never
        # answered.
        timeout_codes = self.DEBUGFS_READ_TIMEOUT_EXIT_CODES

        read_results = self._read_debugfs_tree(node, debugfs_root)

        non_empty_reads = [path for path, size in read_results if size > 0]
        timed_out_reads = [path for path, size in read_results if size in timeout_codes]
        refused_reads = [
            path
            for path, size in read_results
            if size < 0 and size not in timeout_codes
        ]

        # Nothing readable, or nothing but empty files, means the driver
        # published no diagnostic content for this case to read back. That is
        # a property of the driver rather than a fault, so it is reported as
        # not applicable.
        if not read_results:
            raise SkippedException(
                f"driver {driver_name} of SR-IOV VF {vf_slot} exposes "
                f"{debugfs_root} but it holds no readable regular file, so "
                "there is no diagnostic content to read back."
            )
        if not non_empty_reads:
            raise SkippedException(
                f"driver {driver_name} of SR-IOV VF {vf_slot} exposes "
                f"{len(read_results)} readable files under {debugfs_root} and "
                "every one of them is empty, so it publishes no diagnostic "
                "content for this case to read back."
            )

        # A read that comes back with an error is not treated as a fault. Some
        # entries are command interfaces rather than diagnostics and answer
        # only once a command has been staged through them, and a kernel in
        # lockdown refuses every debugfs file that is not read-only. Both are
        # logged for triage instead of asserted on.
        if refused_reads:
            log.info(
                f"{len(refused_reads)} of {len(read_results)} files under "
                f"{debugfs_root} returned an error rather than content, which "
                "is expected of command interfaces and of any writable entry "
                f"when the kernel is locked down: {refused_reads[:5]}"
            )

        # The byte counts are logged rather than asserted on. Drivers differ
        # by orders of magnitude in what they publish, from a single value a
        # few bytes long to a queue dump of tens of KiB, so size carries no
        # verdict.
        log.info(
            f"read {len(read_results)} debugfs files under {debugfs_root}, "
            f"{len(non_empty_reads)} of which returned data"
        )

        assert_that(timed_out_reads).described_as(
            f"these files under {debugfs_root} are advertised as readable by "
            f"{driver_name} but never answered, and were abandoned after "
            f"{self.DEBUGFS_READ_TIMEOUT_SECONDS}s. A debugfs read that hangs "
            "blocks whoever is diagnosing this VF in production, and holds "
            "any driver lock it took for as long as it hangs. Check dmesg for "
            "a lockup or a driver error raised by these reads"
        ).is_empty()

    @TestCaseMetadata(
        description="""
        This case verify VM works well after attached the max sriov nics after
         provision.

        Steps,
        1. Attach 7 extra sriov nic into the VM.
        2. Do the basic sriov testing.
        """,
        priority=2,
        use_new_environment=True,
        requirement=simple_requirement(
            network_interface=schema.NetworkInterfaceOptionSettings(
                data_path=schema.NetworkDataPath.Sriov,
                max_nic_count=search_space.IntRange(min=8),
            ),
        ),
    )
    def verify_sriov_add_max_nics(
        self, log_path: Path, log: Logger, environment: Environment
    ) -> None:
        remove_extra_nics(environment)
        try:
            node = cast(RemoteNode, environment.nodes[0])
            network_interface_feature = node.features[NetworkInterface]
            network_interface_feature.attach_nics(extra_nic_count=7)
            is_ready, tcp_error_code = wait_tcp_port_ready(
                node.connection_info[constants.ENVIRONMENTS_NODES_REMOTE_ADDRESS],
                node.connection_info[constants.ENVIRONMENTS_NODES_REMOTE_PORT],
                log=log,
                timeout=self.TIME_OUT,
            )
            if is_ready:
                initialize_nic_info(environment)
                sriov_basic_test(environment)
            else:
                serial_console = node.features[SerialConsole]
                serial_console.check_panic(
                    saved_path=log_path, stage="after_attach_nics"
                )
                raise TcpConnectionException(
                    node.connection_info[constants.ENVIRONMENTS_NODES_REMOTE_ADDRESS],
                    node.connection_info[constants.ENVIRONMENTS_NODES_REMOTE_PORT],
                    tcp_error_code,
                    "no panic found in serial log after attach nics",
                )
        finally:
            restore_extra_nics(environment)

    @TestCaseMetadata(
        description="""
        This case verify VM works well when provisioning with max sriov nics.

        Steps,
        1. Provision VM with max network interfaces with enabling accelerated network.
        2. Do the basic sriov testing.
        """,
        priority=2,
        requirement=simple_requirement(
            network_interface=schema.NetworkInterfaceOptionSettings(
                data_path=schema.NetworkDataPath.Sriov,
                nic_count=search_space.IntRange(min=2, choose_max_value=True),
            ),
        ),
    )
    def verify_sriov_provision_with_max_nics(self, environment: Environment) -> None:
        initialize_nic_info(environment)
        sriov_basic_test(environment)

    @TestCaseMetadata(
        description="""
        This case verify VM works well when provisioning with max sriov nics.

        Steps,
        1. Provision VM with max network interfaces with enabling accelerated network.
        2. Do the basic sriov testing.
        3. Reboot VM from guest.
        4. Do the basic sriov testing.
        """,
        priority=2,
        requirement=simple_requirement(
            network_interface=schema.NetworkInterfaceOptionSettings(
                data_path=schema.NetworkDataPath.Sriov,
                nic_count=search_space.IntRange(min=2, choose_max_value=True),
            ),
        ),
    )
    def verify_sriov_provision_with_max_nics_reboot(
        self, environment: Environment
    ) -> None:
        initialize_nic_info(environment)
        sriov_basic_test(environment)
        for node in environment.nodes.list():
            node.reboot()
        initialize_nic_info(environment)
        sriov_basic_test(environment)

    @TestCaseMetadata(
        description="""
        This case verify VM works well when provisioning with max sriov nics.

        Steps,
        1. Provision VM with max network interfaces with enabling accelerated network.
        2. Do the basic sriov testing.
        3. Reboot VM from API.
        4. Do the basic sriov testing.
        """,
        priority=2,
        requirement=simple_requirement(
            network_interface=schema.NetworkInterfaceOptionSettings(
                data_path=schema.NetworkDataPath.Sriov,
                nic_count=search_space.IntRange(min=2, choose_max_value=True),
            ),
        ),
    )
    def verify_sriov_provision_with_max_nics_reboot_from_platform(
        self, environment: Environment
    ) -> None:
        initialize_nic_info(environment)
        sriov_basic_test(environment)
        for node in environment.nodes.list():
            start_stop = node.features[StartStop]
            start_stop.restart()
        initialize_nic_info(environment)
        sriov_basic_test(environment)

    @TestCaseMetadata(
        description="""
        This case verify VM works well when provisioning with max sriov nics.

        Steps,
        1. Provision VM with max network interfaces with enabling accelerated network.
        2. Do the basic sriov testing.
        3. Stop and Start VM from API.
        4. Do the basic sriov testing.
        """,
        priority=2,
        requirement=simple_requirement(
            network_interface=schema.NetworkInterfaceOptionSettings(
                data_path=schema.NetworkDataPath.Sriov,
                nic_count=search_space.IntRange(min=2, choose_max_value=True),
            ),
        ),
    )
    def verify_sriov_provision_with_max_nics_stop_start_from_platform(
        self, environment: Environment
    ) -> None:
        initialize_nic_info(environment)
        sriov_basic_test(environment)
        for node in environment.nodes.list():
            start_stop = node.features[StartStop]
            start_stop.stop()
            start_stop.start()
        initialize_nic_info(environment)
        sriov_basic_test(environment)

    @TestCaseMetadata(
        description="""
        This case verify VM works well during remove and load sriov modules.

        Steps,
        1. Provision VM with max network interfaces with enabling accelerated network.
        2. Do the basic sriov testing.
        3. Remove sriov module, check network traffic through synthetic nic.
        4. Load sriov module, check network traffic through VF.
        """,
        priority=1,
        requirement=simple_requirement(
            min_count=2,
            network_interface=schema.NetworkInterfaceOptionSettings(
                data_path=schema.NetworkDataPath.Sriov,
                nic_count=search_space.IntRange(min=2, choose_max_value=True),
            ),
        ),
    )
    def verify_sriov_reload_modules(self, environment: Environment) -> None:
        vm_nics = initialize_nic_info(environment)
        sriov_basic_test(environment)

        module_in_used: Dict[str, List[str]] = {}
        for node in environment.nodes.list():
            module_name_list: List[str] = []
            for module_name in node.nics.get_used_modules(["hv_netvsc"]):
                if node.nics.is_module_reloadable(module_name):
                    module_name_list.extend(node.nics.unload_module(module_name))
            module_in_used[node.name] = module_name_list

        for node in environment.nodes.list():
            if module_in_used[node.name]:
                remove_module = True
            else:
                remove_module = False

        sriov_vf_connection_test(environment, vm_nics, remove_module=remove_module)

        for node in environment.nodes.list():
            for module_name in module_in_used[node.name]:
                node.nics.load_module(module_name)

        vm_nics = initialize_nic_info(environment)
        sriov_vf_connection_test(environment, vm_nics)

    @TestCaseMetadata(
        description="""
        This case verify below two kernel patches.
        1. hv_netvsc: Sync offloading features to VF NIC
           https://github.com/torvalds/linux/commit/68622d071e555e1528f3e7807f30f73311c1acae#diff-007213ba7199932efdb096be47d209a2f83e4d425c486b3adaba861d0a0c80c5 # noqa: E501
        2. hv_netvsc: Allow scatter-gather feature to be tunable
           https://github.com/torvalds/linux/commit/b441f79532ec13dc82d05c55badc4da1f62a6141#diff-007213ba7199932efdb096be47d209a2f83e4d425c486b3adaba861d0a0c80c5 # noqa: E501

        Steps,
        1. Change scatter-gather feature on synthetic nic,
         verify the the feature status sync to the VF dynamically.
        2. Disable and enable sriov,
         check the scatter-gather feature status keep consistent in VF.
        """,
        priority=2,
        requirement=simple_requirement(
            min_count=2,
            network_interface=schema.NetworkInterfaceOptionSettings(
                nic_count=search_space.IntRange(min=3),
                data_path=schema.NetworkDataPath.Sriov,
            ),
            # BSD is unsupported since this is testing to patches to the linux kernel
            unsupported_os=[BSD, Windows],
        ),
    )
    def verify_sriov_ethtool_offload_setting(self, environment: Environment) -> None:
        client_iperf3_log = "iperfResults.log"
        server_node = cast(RemoteNode, environment.nodes[0])
        client_node = cast(RemoteNode, environment.nodes[1])
        client_ethtool = client_node.tools[Ethtool]
        vm_nics = initialize_nic_info(environment)

        # skip test if scatter-gather can't be updated
        for client_nic_info in vm_nics[client_node.name].values():
            device_sg_settings = client_ethtool.get_device_sg_settings(
                client_nic_info.name, True
            )
            if device_sg_settings.sg_fixed:
                raise SkippedException(
                    "scatter-gather is fixed, it cannot be changed for device"
                    f" {client_nic_info.name}. Skipping test."
                )
            else:
                break
        # save original enabled features
        device_enabled_features_origin = client_ethtool.get_all_device_enabled_features(
            True
        )

        # run iperf3 on server side and client side
        # iperfResults.log stored client side log
        source_iperf3 = server_node.tools[Iperf3]
        dest_iperf3 = client_node.tools[Iperf3]
        source_iperf3.run_as_server_async()
        dest_iperf3.run_as_client_async(
            server_ip=server_node.internal_address,
            log_file=client_iperf3_log,
            run_time_seconds=self.TIME_OUT,
        )

        # wait for a while then check any error shown up in iperfResults.log
        dest_cat = client_node.tools[Cat]
        iperf_log = dest_cat.read(client_iperf3_log, sudo=True, force_run=True)
        assert_that(iperf_log).does_not_contain("error")

        # disable and enable VF in pci level
        disable_enable_devices(environment)
        # check VF still paired with synthetic nic
        vm_nics = initialize_nic_info(environment)

        # get the enabled features after disable and enable VF
        # make sure there is not any change
        device_enabled_features_after = client_ethtool.get_all_device_enabled_features(
            True
        )
        assert_that(device_enabled_features_origin[0].enabled_features).is_equal_to(
            device_enabled_features_after[0].enabled_features
        )

        # set on for scatter-gather feature for synthetic nic
        # verify vf scatter-gather feature has value 'on'
        for client_nic_info in vm_nics[client_node.name].values():
            new_settings = client_ethtool.change_device_sg_settings(
                client_nic_info.name, True
            )
            device_vf_sg_settings = client_ethtool.get_device_sg_settings(
                client_nic_info.pci_device_name, True
            )
            assert_that(
                new_settings.sg_setting,
                "sg setting is not sync into VF.",
            ).is_equal_to(device_vf_sg_settings.sg_setting)

        # set off for scatter-gather feature for synthetic nic
        # verify vf scatter-gather feature has value 'off'
        for client_nic_info in vm_nics[client_node.name].values():
            new_settings = client_ethtool.change_device_sg_settings(
                client_nic_info.name, False
            )
            device_vf_sg_settings = client_ethtool.get_device_sg_settings(
                client_nic_info.pci_device_name, True
            )
            assert_that(
                new_settings.sg_setting,
                "sg setting is not sync into VF.",
            ).is_equal_to(device_vf_sg_settings.sg_setting)

        #  disable and enable VF in pci level
        disable_enable_devices(environment)
        # check VF still paired with synthetic nic
        vm_nics = initialize_nic_info(environment)

        # check VF's scatter-gather feature keep consistent with previous status
        for client_nic_info in vm_nics[client_node.name].values():
            device_vf_sg_settings = client_ethtool.get_device_sg_settings(
                client_nic_info.pci_device_name, True
            )
            assert_that(
                device_vf_sg_settings.sg_setting,
                "sg setting is not sync into VF.",
            ).is_equal_to(False)

        # disable and enable sriov in network interface level
        sriov_disable_enable(environment, 3)
        # check VF still paired with synthetic nic
        vm_nics = initialize_nic_info(environment)

        # check VF's scatter-gather feature keep consistent with previous status
        for client_nic_info in vm_nics[client_node.name].values():
            device_vf_sg_settings = client_ethtool.get_device_sg_settings(
                client_nic_info.pci_device_name, True
            )
            assert_that(
                device_vf_sg_settings.sg_setting,
                "sg setting is not sync into VF.",
            ).is_equal_to(False)

        # reload sriov modules
        if reload_modules(environment):
            # check VF still paired with synthetic nic
            vm_nics = initialize_nic_info(environment)

            # check VF's scatter-gather feature keep consistent with previous status
            for client_nic_info in vm_nics[client_node.name].values():
                device_vf_sg_settings = client_ethtool.get_device_sg_settings(
                    client_nic_info.pci_device_name, True
                )
                assert_that(
                    device_vf_sg_settings.sg_setting,
                    "sg setting is not sync into VF.",
                ).is_equal_to(False)

        # check there is no error happen in iperf3 log
        # after above operations
        dest_cat = client_node.tools[Cat]
        iperf_log = dest_cat.read(client_iperf3_log, sudo=True, force_run=True)
        assert_that(iperf_log).does_not_contain("error")

    @TestCaseMetadata(
        description="""
        This test case verifies that irq rebalance is running.
        When irqbalance is in debug mode, it will log “Selecting irq xxx for
        rebalancing” when it selects an irq for rebalancing. We expect to see
        this irq rebalancing when VM is under heavy network load.

        An issue was previously seen in irqbalance 1.8.0-1build1 on Ubuntu.
        When IRQ rebalance is not running, we expect to see poor network
        performance and high package loss. Contact the distro publisher if
        this is the case.

        Steps,
        1. Stop irqbalance service.
        2. Start irqbalance as a background process with debug mode.
        3. Generate some network traffic.
        4. Check irqbalance output for “Selecting irq xxx for rebalancing”.
        """,
        priority=2,
        requirement=simple_requirement(
            min_count=2,
            min_core_count=4,
            network_interface=features.Sriov(),
        ),
    )
    def verify_irqbalance(self, environment: Environment, log: Logger) -> None:
        err_msg: str = ""

        server_node = cast(RemoteNode, environment.nodes[0])
        client_node = cast(RemoteNode, environment.nodes[1])

        if (
            server_node.execute(
                "command -v irqbalance", shell=True, sudo=True
            ).exit_code
            != 0
        ):
            if not isinstance(
                server_node.os, Posix
            ) or not server_node.os.is_package_in_repo("irqbalance"):
                raise SkippedException("irqbalance is not available")
            server_node.os.install_packages("irqbalance")

        # Get the irqbalance version if we can
        if isinstance(server_node.os, Posix):
            try:
                log.debug(
                    "irqbalance version: "
                    f"{server_node.os.get_package_information('irqbalance')}"
                )
            except Exception as e:
                log.debug("irqbalance version: not found")
                err_msg += (
                    "\nPotential issues getting irqbalance version, "
                    "check logs for details."
                )
                log.debug("Exception: " + str(e))

        server_node.tools[Service].stop_service("irqbalance")

        irqbalance = server_node.execute_async("irqbalance --debug", sudo=True)

        server_iperf3 = server_node.tools[Iperf3]
        client_iperf3 = client_node.tools[Iperf3]

        server_iperf3.run_as_server_async()
        try:
            client_iperf3.run_as_client(
                server_ip=server_node.internal_address,
                run_time_seconds=240,
                parallel_number=128,
                client_ip=client_node.internal_address,
            )
        except AssertionError as e:
            # We don't care about the iperf3 results, we just want to generate
            # network traffic.
            log.debug(f"iperf3 failed: {e}")
            err_msg += "\nPotential issues running iperf3, check logs for details."

        irqbalance.kill()
        # The kill() above sends SIGKILL to the spur-tracked process (the
        # sudo/sh wrapper), but irqbalance itself is a child that can survive
        # as an orphan.  Explicitly kill it by name to ensure it is gone
        # before waiting for the result, so wait_result() does not time out.
        server_node.tools[Kill].by_name("irqbalance", ignore_not_exist=True)
        result = irqbalance.wait_result(raise_on_timeout=False)

        # Check that irqbalance actively rebalanced an IRQ.
        selecting_match = re.search(
            "Selecting irq [0-9]+ for rebalancing",
            result.stdout,
        )
        if not selecting_match:
            # On high-core-count VMs with managed IRQs (e.g. MANA NICs on v6
            # SKUs), the kernel handles IRQ affinity and irqbalance correctly
            # determines no rebalancing is needed. In this case, verify that
            # irqbalance successfully completed at least one scan cycle by
            # checking for interrupt enumeration output.
            assert re.search(
                r"Interrupt \d+ node_num",
                result.stdout,
            ), (
                "irqbalance is not rebalancing irqs" + err_msg
            )
            log.debug(
                "irqbalance did not select any IRQ for rebalancing "
                "(likely managed IRQs on high-core-count VM), "
                "but scan cycle completed successfully"
            )

    @TestCaseMetadata(
        description="""
        This case is to verify interrupts count increased after network traffic
         went through the VF, if CPU is less than 8, it can't verify the interrupts
         spread to CPU evenly, when CPU is more than 16, the traffic is too light to
         make sure interrupts distribute to every CPU.

        Steps,
        1. Start iperf3 on server node.
        2. Get initial interrupts sum per irq and cpu number on client node.
        3. Start iperf3 for 120 seconds with 128 threads on client node.
        4. Get final interrupts sum per irq number on client node.
        5. Compare interrupts changes, expected to see interrupts increased.
        6. Get final interrupts sum per cpu on client node.
        7. Collect cpus which don't have interrupts count increased.
        8. Compare interrupts count changes, expected half of cpus' interrupts
         increased.
        """,
        priority=2,
        requirement=node_requirement(
            node=schema.NodeSpace(
                node_count=2,
                core_count=search_space.IntRange(min=8, max=16),
                network_interface=features.Sriov(),
            )
        ),
    )
    def verify_sriov_interrupts_change(self, environment: Environment) -> None:
        server_node = cast(RemoteNode, environment.nodes[0])
        client_node = cast(RemoteNode, environment.nodes[1])
        client_lscpu = client_node.tools[Lscpu]
        client_thread_count = client_lscpu.get_thread_count()

        vm_nics = initialize_nic_info(environment)

        server_iperf3 = server_node.tools[Iperf3]
        client_iperf3 = client_node.tools[Iperf3]
        # 1. Start iperf3 on server node.
        server_iperf3.run_as_server_async()
        client_interrupt_inspector = client_node.tools[InterruptInspector]
        for _, client_nic_info in vm_nics[client_node.name].items():
            if client_nic_info.is_pci_module_enabled:
                # Skip InfiniBand and NICs without IP (enslaved VFs, etc.)
                if client_nic_info.is_infiniband or not client_nic_info.ip_addr:
                    continue
                # 2. Get initial interrupts sum per irq and cpu number on client node.
                # only collect 'Completion Queue Interrupts' irqs
                initial_pci_interrupts_by_irqs = (
                    client_interrupt_inspector.sum_cpu_counter_by_irqs(
                        client_nic_info.pci_slot,
                        exclude_key_words=["pages", "cmd", "async", "hwc"],
                    )
                )

                initial_pci_interrupts_by_cpus = (
                    client_interrupt_inspector.sum_cpu_counter_by_index(
                        client_nic_info.pci_slot
                    )
                )
                if isinstance(client_node.os, BSD):
                    assert_that(len(initial_pci_interrupts_by_cpus)).described_as(
                        "initial cpu count of interrupts should be equal to cpu count"
                        " plus one to account for control queue"
                    ).is_equal_to(client_thread_count + 1)
                else:
                    assert_that(len(initial_pci_interrupts_by_cpus)).described_as(
                        "initial cpu count of interrupts should be equal to cpu count"
                    ).is_equal_to(client_thread_count)
                matched_server_nic_info: Optional[NicInfo] = None
                for _, server_nic_info in vm_nics[server_node.name].items():
                    # Skip NICs without IP addresses (IB, enslaved VFs, etc.)
                    if not server_nic_info.ip_addr:
                        continue
                    if server_nic_info.is_infiniband:
                        continue
                    if (
                        server_nic_info.ip_addr.rsplit(".", maxsplit=1)[0]
                        == client_nic_info.ip_addr.rsplit(".", maxsplit=1)[0]
                    ):
                        matched_server_nic_info = server_nic_info
                        break
                assert matched_server_nic_info, (
                    "not found the server nic has the same subnet of"
                    f" {client_nic_info.ip_addr}"
                )

                # 3. Start iperf3 for 120 seconds with 128 threads on client node.
                client_iperf3.run_as_client(
                    server_ip=matched_server_nic_info.ip_addr,
                    run_time_seconds=120,
                    parallel_number=128,
                    client_ip=client_nic_info.ip_addr,
                )
                # 4. Get final interrupts sum per irq number on client node.
                final_pci_interrupts_by_irqs = (
                    client_interrupt_inspector.sum_cpu_counter_by_irqs(
                        client_nic_info.pci_slot,
                        exclude_key_words=["pages", "cmd", "async", "hwc"],
                    )
                )
                assert_that(len(final_pci_interrupts_by_irqs)).described_as(
                    "final irqs count should be greater than 0"
                ).is_greater_than(0)
                for init_interrupts_irq in initial_pci_interrupts_by_irqs:
                    init_irq_number = list(init_interrupts_irq)[0]
                    init_interrupts_value = init_interrupts_irq[init_irq_number]
                    for final_interrupts in final_pci_interrupts_by_irqs:
                        final_irq_number = list(final_interrupts)[0]
                        final_interrupts_value = final_interrupts[final_irq_number]
                        if init_irq_number == final_irq_number:
                            break
                    # 5. Compare interrupts changes, expected to see interrupts
                    # increased.
                    assert_that(final_interrupts_value).described_as(
                        f"irq {init_irq_number} didn't have an increased interrupts "
                        " count after iperf3 run!"
                    ).is_greater_than(init_interrupts_value)
                # 6. Get final interrupts sum per cpu on client node.
                final_pci_interrupts_by_cpus = (
                    client_interrupt_inspector.sum_cpu_counter_by_index(
                        client_nic_info.pci_slot
                    )
                )
                if isinstance(client_node.os, BSD):
                    assert_that(len(final_pci_interrupts_by_cpus)).described_as(
                        "initial cpu count of interrupts should be equal to cpu count"
                        " plus one to account for control queue"
                    ).is_equal_to(client_thread_count + 1)
                else:
                    assert_that(len(final_pci_interrupts_by_cpus)).described_as(
                        "initial cpu count of interrupts should be equal to cpu count"
                    ).is_equal_to(client_thread_count)
                unused_cpu = 0
                for (
                    cpu,
                    init_interrupts_value,
                ) in initial_pci_interrupts_by_cpus.items():
                    final_interrupts_value = final_pci_interrupts_by_cpus[cpu]
                    # 7. Collect cpus which don't have interrupts count increased.
                    if final_interrupts_value == init_interrupts_value:
                        unused_cpu += 1
                # 8. Compare interrupts count changes, expected half of cpus' interrupts
                #    increased.
                assert_that(client_thread_count / 2).described_as(
                    f"More than half of the vCPUs {unused_cpu} didn't have increased "
                    "interrupt count!"
                ).is_greater_than(unused_cpu)

    def after_case(self, log: Logger, **kwargs: Any) -> None:
        environment: Environment = kwargs.pop("environment")
        cleanup_iperf3(environment)

    def _read_debugfs_tree(
        self, node: Node, debugfs_root: str
    ) -> List[Tuple[str, int]]:
        # Emits "<byte_count>\t<path>" per readable file and
        # "ERR<exit_code>\t<path>" per file whose read fails.
        scratch = "/tmp/lisa_debugfs_read"
        # -k escalates to KILL a second after the read declines to stop, so a
        # read that ignores the first signal cannot stall the whole walk.
        per_file = (
            f"if timeout -k 1 {self.DEBUGFS_READ_TIMEOUT_SECONDS} "
            f'head -c {self.DEBUGFS_READ_CAP_BYTES} "$1" > "$2" 2>/dev/null; '
            'then printf "%s\\t%s\\n" "$(wc -c < "$2")" "$1"; '
            'else printf "ERR%s\\t%s\\n" "$?" "$1"; fi'
        )
        result = node.execute(
            f"find '{debugfs_root}' -type f -perm -u+r "
            f"-exec sh -c '{per_file}' _ {{}} '{scratch}' \\;; "
            f"rm -f '{scratch}'",
            sudo=True,
            shell=True,
            no_info_log=True,
        )
        result.assert_exit_code(
            0,
            message=(
                f"failed to enumerate and read debugfs files under "
                f"{debugfs_root}. Verify the path exists and is readable "
                "with sudo."
            ),
            include_output=True,
        )

        read_results: List[Tuple[str, int]] = []
        for line in result.stdout.splitlines():
            token, _, path = line.partition("\t")
            if not path:
                continue
            if token.startswith("ERR"):
                # A failed read is carried as the negated exit code, which
                # keeps one integer per file while preserving the reason.
                try:
                    read_results.append((path, -int(token[len("ERR") :])))
                except ValueError:
                    read_results.append((path, -1))
                continue
            try:
                read_results.append((path, int(token)))
            except ValueError:
                # Unexpected output for this path, treated as a failed read.
                read_results.append((path, -1))
        return read_results
