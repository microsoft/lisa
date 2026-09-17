# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, cast

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
    Ethtool,
    Firewall,
    InterruptInspector,
    Ip,
    Iperf3,
    Journalctl,
    Kill,
    Lscpu,
    Ping,
    Service,
)
from lisa.util import (
    LisaException,
    LisaTimeoutException,
    UnsupportedDistroException,
    UnsupportedOperationException,
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
    COALESCE_PARAMETER = "rx-cqe-frames"
    # CQE packing implementations commonly expose single-frame mode and a
    # small fixed group size. Probe alternatives and use the first value the
    # driver accepts rather than assuming every device has the same range.
    COALESCE_CANDIDATES = (1, 4, 8, 2, 16)
    COALESCE_VALUE_REJECTION_PATTERNS = (
        "invalid argument",
        "not supported",
        "out of range",
    )
    # The netlink attribute is a u32, so this value cannot be represented and
    # must be rejected rather than truncated or clamped.
    INVALID_COALESCE_VALUE = 1 << 32
    # MANA uses rx_0_packets while mlx5 uses rx0_packets. Match only those base
    # queue packet counters so TSO and inner-packet counters are not included.
    _RX_QUEUE_PACKET_COUNTER_PATTERN = re.compile(r"^(?:rx_\d+_packets|rx\d+_packets)$")
    _TX_QUEUE_PACKET_COUNTER_PATTERN = re.compile(r"^(?:tx_\d+_packets|tx\d+_packets)$")
    # A successful echo request/reply contributes one TX and one RX packet.
    # One thousand packets is well above the ambient SSH traffic seen during
    # the sample interval, so a passing delta is attributable to this workload.
    _STATISTICS_PING_COUNT = 1000
    # GRO and driver receive coalescing can represent multiple echo replies in
    # one RX packet counter increment. Require at least half of the injected
    # count, which remains far above the measured ambient traffic.
    _MINIMUM_STATISTICS_PACKET_DELTA = _STATISTICS_PING_COUNT // 2
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
        This test case verifies if the ring buffer settings of an SR-IOV VF
        can be changed with ethtool.

        Steps:
        1. Get the current ring buffer settings of every VF on the node.
        2. Change the rx and tx value to new_values using ethtool.
        3. Get the settings again and validate the current rx and tx
           values are equal to the new_values assigned.
        4. Revert back the rx and tx value to their original values.

        This test is generated by the lisa_test_writer prompt.
        """,
        priority=2,
        maturity="preview",
        requirement=simple_requirement(
            network_interface=features.Sriov(),
            unsupported_os=[BSD, Windows],
        ),
        tags=["ai-generated"],
    )
    def verify_sriov_ethtool_ring_buffer_settings(
        self, node: Node, log: Logger
    ) -> None:
        ethtool = node.tools[Ethtool]
        vf_nics = self._get_vf_nics(node, log, "ring buffer settings")

        for vf_nic in vf_nics:
            try:
                interface_settings = ethtool.get_device_ring_buffer_settings(
                    vf_nic, force_run=True
                )
            except UnsupportedOperationException as e:
                raise SkippedException(e)

            original_rx = int(interface_settings.current_ring_buffer_settings["RX"])
            original_tx = int(interface_settings.current_ring_buffer_settings["TX"])
            max_rx = int(interface_settings.max_ring_buffer_settings["RX"])
            max_tx = int(interface_settings.max_ring_buffer_settings["TX"])

            expected_rx = self._get_supported_ring_size(original_rx, max_rx)
            expected_tx = self._get_supported_ring_size(original_tx, max_tx)

            actual_settings = ethtool.change_device_ring_buffer_settings(
                vf_nic, expected_rx, expected_tx
            )

            try:
                # A VF driver reports back the ring size it was given, so
                # this is an equality check rather than a range.
                assert_that(
                    int(actual_settings.current_ring_buffer_settings["RX"]),
                    "Changing RX Ringbuffer setting didn't succeed",
                ).is_equal_to(expected_rx)
                assert_that(
                    int(actual_settings.current_ring_buffer_settings["TX"]),
                    "Changing TX Ringbuffer setting didn't succeed",
                ).is_equal_to(expected_tx)
            finally:
                # Restore even when the checks above fail, so a failure does
                # not hand a resized ring to the cases that follow.
                reverted_settings = ethtool.change_device_ring_buffer_settings(
                    vf_nic, original_rx, original_tx
                )

            assert_that(
                int(reverted_settings.current_ring_buffer_settings["RX"]),
                "Reverting RX Ringbuffer setting to original value didn't succeed",
            ).is_equal_to(original_rx)
            assert_that(
                int(reverted_settings.current_ring_buffer_settings["TX"]),
                "Reverting TX Ringbuffer setting to original value didn't succeed",
            ).is_equal_to(original_tx)

    def _get_vf_nics(self, node: Node, log: Logger, purpose: str) -> List[str]:
        node.nics.reload()
        # A VF is reachable either standalone or as the lower device of a
        # synthetic NIC, so select on AN being enabled and let pci_device_name
        # resolve to whichever applies. Every VF is returned, so a multi vport
        # VM is validated end to end.
        vf_nics = list(
            dict.fromkeys(
                nic.pci_device_name
                for nic in node.nics.nics.values()
                if nic.is_pci_module_enabled and not nic.is_infiniband
            )
        )
        if not vf_nics:
            raise SkippedException(
                f"No SR-IOV VF interface found on the node, {purpose} "
                "cannot be validated."
            )
        log.info(f"Validating {purpose} on VF interfaces {vf_nics}")
        return vf_nics

    def _get_supported_ring_size(self, current: int, maximum: int) -> int:
        # One step rather than the maximum: rings are preallocated, so the
        # maximum can cost about 1 GB on a 32 queue VF and fail on -ENOMEM.
        # Powers of two because a driver may round the request up to one.
        ceiling = 1 << (maximum.bit_length() - 1)
        step_up = 1 << current.bit_length()
        if step_up <= ceiling:
            return step_up
        # Already at the largest power of two the device allows.
        return max(ceiling // 2, 1)

    def _require_device_up(self, ip: Ip, vf_nic: str, log: Logger) -> None:
        # Several ethtool set operations, RSS in particular, are rejected with
        # EOPNOTSUPP while the port is down, so the interface has to be up
        # before the settings are exercised.
        if ip.is_device_up(vf_nic):
            return
        log.info(f"{vf_nic} is down, bringing it up before changing its settings.")
        ip.up(vf_nic)
        check_till_timeout(
            lambda: ip.is_device_up(vf_nic) is True,
            timeout_message=f"{vf_nic} did not come up, its settings cannot be "
            "changed while the port is down.",
        )

    @TestCaseMetadata(
        description="""
        This case verifies the SR-IOV VF driver reports and applies its RSS hash
        key correctly.

        The RSS hash key determines how received traffic is spread across
        queues. Operators change it to alter that distribution, so it must
        round-trip exactly.

        Steps,
        1. Get the VF interface and read its current RSS hash key.
        2. Verify the key is a valid colon-separated sequence of bytes.
        3. Set a new hash key of the same length and read it back.
        4. Verify the key read back matches the key written exactly.
        5. Restore the original hash key and verify the interface remains up.

        This test is generated by the lisa_test_writer prompt.
        """,
        priority=2,
        maturity="preview",
        requirement=simple_requirement(
            network_interface=features.Sriov(),
            unsupported_os=[BSD, Windows],
        ),
        tags=["ai-generated"],
    )
    def verify_sriov_ethtool_rss_hash_key(self, node: Node, log: Logger) -> None:
        ethtool = node.tools[Ethtool]
        ip = node.tools[Ip]

        vf_nics = self._get_vf_nics(node, log, "RSS hash key")

        for vf_nic in vf_nics:
            self._verify_vf_rss_hash_key(ethtool, ip, vf_nic, log)

    def _verify_vf_rss_hash_key(
        self, ethtool: Ethtool, ip: Ip, vf_nic: str, log: Logger
    ) -> None:
        device_was_up = ip.is_device_up(vf_nic)
        try:
            self._require_device_up(ip, vf_nic, log)
            try:
                original = ethtool.get_device_rss_hash_key(vf_nic, force_run=True)
            except UnsupportedOperationException as identifier:
                raise SkippedException(identifier) from identifier

            original_key = original.rss_hash_key.lower()
            log.debug(f"{vf_nic} RSS hash key: {original_key}")
            assert_that(original_key).described_as(
                f"{vf_nic} reported an empty RSS hash key, the VF driver does not "
                "expose the key that steers received traffic."
            ).is_not_empty()

            key_bytes = original_key.split(":")
            malformed = [item for item in key_bytes if len(item) != 2]
            assert_that(malformed).described_as(
                f"{vf_nic} RSS hash key contains fields that are not single "
                f"hex bytes: {malformed}."
            ).is_empty()

            new_key = self._get_alternate_hash_key(key_bytes)
            log.info(f"Setting {vf_nic} RSS hash key to {new_key}")
            changed = ethtool.change_device_rss_hash_key(vf_nic, new_key)
            try:
                assert_that(changed.rss_hash_key.lower()).described_as(
                    f"{vf_nic} did not apply the RSS hash key exactly as written, "
                    "the key does not round-trip through the driver."
                ).is_equal_to(new_key)
            finally:
                log.info(f"Restoring {vf_nic} RSS hash key to {original_key}")
                restored = ethtool.change_device_rss_hash_key(vf_nic, original_key)

            assert_that(restored.rss_hash_key.lower()).described_as(
                f"{vf_nic} RSS hash key was not restored to its original value."
            ).is_equal_to(original_key)
            assert_that(ip.is_device_up(vf_nic)).described_as(
                f"{vf_nic} is not up after restoring the RSS hash key."
            ).is_true()
            log.info(f"RSS hash key of {vf_nic} validated and restored.")
        finally:
            if ip.is_device_up(vf_nic) != device_was_up:
                original_state = "up" if device_was_up else "down"
                log.info(f"Restoring {vf_nic} to its original {original_state} state.")
                if device_was_up:
                    ip.up(vf_nic)
                else:
                    ip.down(vf_nic)

    def _get_alternate_hash_key(self, key_bytes: List[str]) -> str:
        # Reversing keeps the exact byte count the driver expects. A
        # palindromic key would map to itself and make the round-trip check
        # meaningless, so flip the first byte in that case.
        new_bytes = list(reversed(key_bytes))
        if new_bytes == key_bytes:
            new_bytes[0] = f"{int(new_bytes[0], 16) ^ 0xFF:02x}"
        return ":".join(new_bytes)

    @TestCaseMetadata(
        description="""
        This case verifies the SR-IOV VF driver reports its RSS indirection
        table and accepts a valid redistribution across receive queues.

        The indirection table maps hash buckets to receive queues. The driver
        must report a consistent table and reject entries pointing at queues
        that do not exist.

        Steps,
        1. Get the VF interface and read its RSS indirection table.
        2. Verify the parsed rows are complete and every entry indexes a valid
           receive queue.
        3. Redistribute the table evenly across a subset of queues and verify
           it is applied.
        4. Try to redistribute across more queues than the device has and
           verify it is rejected.
        5. Restore the driver default and verify it matches the original table.

        This test is generated by the lisa_test_writer prompt.
        """,
        priority=2,
        maturity="preview",
        requirement=simple_requirement(
            network_interface=features.Sriov(),
            unsupported_os=[BSD, Windows],
        ),
        tags=["ai-generated"],
    )
    def verify_sriov_ethtool_rss_indirection_table(
        self, node: Node, log: Logger
    ) -> None:
        ethtool = node.tools[Ethtool]
        ip = node.tools[Ip]

        vf_nics = self._get_vf_nics(node, log, "RSS indirection table")

        for vf_nic in vf_nics:
            self._verify_vf_rss_indirection_table(ethtool, ip, vf_nic, log)

    def _verify_vf_rss_indirection_table(
        self, ethtool: Ethtool, ip: Ip, vf_nic: str, log: Logger
    ) -> None:
        device_was_up = ip.is_device_up(vf_nic)
        try:
            self._require_device_up(ip, vf_nic, log)
            try:
                original = ethtool.get_device_rss_indirection_table(
                    vf_nic, force_run=True
                )
            except UnsupportedOperationException as identifier:
                raise SkippedException(identifier) from identifier

            ring_count = original.rx_ring_count
            log.debug(
                f"{vf_nic} RSS indirection table holds {len(original.table)} "
                f"entries across {ring_count} RX ring(s)"
            )

            # The entry count and RX ring count are different numbers in the
            # same output, so each is checked against its own source.
            assert_that(original.table).described_as(
                f"{vf_nic} returned an RSS indirection table whose entry count "
                f"disagrees with the {original.indirection_size} entries its own "
                "row offsets report."
            ).is_length(original.indirection_size)
            assert_that(ring_count).described_as(
                f"{vf_nic} reported zero RX rings, the indirection table cannot "
                "reference any receive queue."
            ).is_greater_than(0)
            out_of_range = sorted(
                {entry for entry in original.table if entry < 0 or entry >= ring_count}
            )
            assert_that(out_of_range).described_as(
                f"{vf_nic} RSS indirection table points at receive queues that "
                f"do not exist, the device has {ring_count} RX ring(s)."
            ).is_empty()

            if ring_count < 2:
                raise SkippedException(
                    f"{vf_nic} exposes {ring_count} RX ring, the indirection table "
                    "cannot be redistributed across a subset of queues."
                )

            target_queues = ring_count // 2
            try:
                self._redistribute_indirection_table(
                    ethtool, vf_nic, target_queues, log
                )
                self._reject_oversized_indirection_table(
                    ethtool, vf_nic, ring_count, log
                )
            finally:
                log.info(f"Restoring {vf_nic} RSS indirection table to the default")
                restored = ethtool.change_device_rss_indirection_table(
                    vf_nic, "default"
                )

            assert_that(restored.table).described_as(
                f"{vf_nic} RSS indirection table was not restored to the driver "
                "default it reported before the test."
            ).is_equal_to(original.table)
            assert_that(ip.is_device_up(vf_nic)).described_as(
                f"{vf_nic} is not up after restoring the RSS indirection table."
            ).is_true()
            log.info(f"RSS indirection table of {vf_nic} validated and restored.")
        finally:
            if ip.is_device_up(vf_nic) != device_was_up:
                original_state = "up" if device_was_up else "down"
                log.info(f"Restoring {vf_nic} to its original {original_state} state.")
                if device_was_up:
                    ip.up(vf_nic)
                else:
                    ip.down(vf_nic)

    def _redistribute_indirection_table(
        self, ethtool: Ethtool, vf_nic: str, target_queues: int, log: Logger
    ) -> None:
        log.info(
            f"Spreading {vf_nic} RSS indirection table evenly across "
            f"{target_queues} receive queue(s)"
        )
        changed = ethtool.change_device_rss_indirection_table(
            vf_nic, f"equal {target_queues}"
        )
        assert_that(sorted(set(changed.table))).described_as(
            f"{vf_nic} did not restrict the RSS indirection table to the first "
            f"{target_queues} receive queue(s)."
        ).is_equal_to(list(range(target_queues)))

        occurrences = [changed.table.count(queue) for queue in range(target_queues)]
        assert_that(max(occurrences) - min(occurrences)).described_as(
            f"{vf_nic} spread the RSS indirection table unevenly across "
            f"{target_queues} queue(s), entries per queue: {occurrences}."
        ).is_less_than_or_equal_to(1)

    def _reject_oversized_indirection_table(
        self, ethtool: Ethtool, vf_nic: str, ring_count: int, log: Logger
    ) -> None:
        before = ethtool.get_device_rss_indirection_table(vf_nic, force_run=True)
        too_many = ring_count + 1
        log.info(
            f"Spreading {vf_nic} RSS indirection table across {too_many} queues, "
            "it is expected to fail."
        )
        result = ethtool.set_device_rss_indirection_table(vf_nic, f"equal {too_many}")
        assert_that(result.exit_code).described_as(
            f"{vf_nic} accepted an RSS indirection table spread across "
            f"{too_many} queues while the device exposes only {ring_count} RX "
            "ring(s), entries pointing at a missing queue drop traffic."
        ).is_not_equal_to(0)

        after = ethtool.get_device_rss_indirection_table(vf_nic, force_run=True)
        assert_that(after.table).described_as(
            f"{vf_nic} RSS indirection table changed after a rejected request."
        ).is_equal_to(before.table)

    @TestCaseMetadata(
        description="""
        This case verifies the SR-IOV VF driver reports and applies receive CQE
        coalescing settings correctly.

        CQE coalescing reduces completion traffic by representing several
        received frames with one completion entry. The driver must apply valid
        group sizes and reject values outside its supported modes.

        Steps,
        1. Get every VF interface and read its receive CQE coalescing setting.
        2. Change the setting to another value accepted by the driver and
           verify the value is reported back.
        3. Try an unsupported value and verify it is rejected without changing
           the active setting.
        4. Restore the original setting and interface state.

        This test is generated by the lisa_test_writer prompt.
        """,
        priority=2,
        maturity="preview",
        requirement=simple_requirement(
            network_interface=features.Sriov(),
            unsupported_os=[BSD, Windows],
        ),
        tags=["ai-generated"],
    )
    def verify_sriov_ethtool_coalesce_settings(self, node: Node, log: Logger) -> None:
        ethtool = node.tools[Ethtool]
        ip = node.tools[Ip]
        vf_nics = self._get_vf_nics(node, log, "receive CQE coalescing settings")

        for vf_nic in vf_nics:
            self._verify_vf_coalesce_settings(ethtool, ip, vf_nic, log)

    def _verify_vf_coalesce_settings(
        self, ethtool: Ethtool, ip: Ip, vf_nic: str, log: Logger
    ) -> None:
        parameter = self.COALESCE_PARAMETER
        device_was_up = ip.is_device_up(vf_nic)
        try:
            self._require_device_up(ip, vf_nic, log)
            # An older client cannot distinguish a missing netlink attribute
            # from missing driver support, so select a capable client first.
            if not ethtool.supports_rx_cqe_frames():
                log.info(
                    f"The installed ethtool does not expose {parameter}; building "
                    "a release that supports the kernel attribute."
                )
                try:
                    ethtool.ensure_rx_cqe_frames_support()
                except UnsupportedDistroException as identifier:
                    raise SkippedException(identifier) from identifier

            try:
                original = ethtool.get_device_coalesce_settings(vf_nic, force_run=True)
            except UnsupportedOperationException as identifier:
                raise SkippedException(identifier) from identifier

            log.debug(
                f"{vf_nic} coalescing settings: {original.settings}; "
                f"not applicable: {original.not_applicable}"
            )
            if parameter not in original.settings:
                raise SkippedException(
                    f"{vf_nic} does not expose {parameter} as a numeric tunable. "
                    f"It reports {sorted(original.settings)} as numeric and "
                    f"{original.not_applicable} as not applicable."
                )
            original_value = original.settings[parameter]

            try:
                target = self._set_alternate_coalesce_value(
                    ethtool, vf_nic, original_value
                )
                log.info(
                    f"Changed {vf_nic} {parameter} from {original_value} to {target}"
                )
                changed = ethtool.get_device_coalesce_settings(vf_nic, force_run=True)
                assert_that(changed.settings[parameter]).described_as(
                    f"{vf_nic} accepted {parameter}={target} but did not report "
                    "the value as active."
                ).is_equal_to(target)

                self._reject_invalid_coalesce_value(
                    ethtool, vf_nic, parameter, target, log
                )
            finally:
                active = ethtool.get_device_coalesce_settings(vf_nic, force_run=True)
                if active.settings.get(parameter) != original_value:
                    log.info(f"Restoring {vf_nic} {parameter} to {original_value}")
                    ethtool.set_device_coalesce_setting(
                        vf_nic, parameter, original_value
                    ).assert_exit_code(
                        message=f"Couldn't restore {vf_nic} {parameter} to "
                        f"{original_value}. Inspect the driver and ethtool error "
                        "output."
                    )

            restored = ethtool.get_device_coalesce_settings(vf_nic, force_run=True)
            assert_that(restored.settings[parameter]).described_as(
                f"{vf_nic} {parameter} was not restored to its original value."
            ).is_equal_to(original_value)
            assert_that(ip.is_device_up(vf_nic)).described_as(
                f"{vf_nic} is not up after restoring its CQE coalescing setting."
            ).is_true()
            log.info(f"CQE coalescing setting of {vf_nic} validated and restored.")
        finally:
            if ip.is_device_up(vf_nic) != device_was_up:
                original_state = "up" if device_was_up else "down"
                log.info(f"Restoring {vf_nic} to its original {original_state} state.")
                if device_was_up:
                    ip.up(vf_nic)
                else:
                    ip.down(vf_nic)

    def _set_alternate_coalesce_value(
        self, ethtool: Ethtool, vf_nic: str, original_value: int
    ) -> int:
        parameter = self.COALESCE_PARAMETER
        for candidate in self.COALESCE_CANDIDATES:
            if candidate == original_value:
                continue
            result = ethtool.set_device_coalesce_setting(vf_nic, parameter, candidate)
            if result.exit_code == 0:
                return candidate
            output = f"{result.stdout}\n{result.stderr}".lower()
            if not any(
                pattern in output for pattern in self.COALESCE_VALUE_REJECTION_PATTERNS
            ):
                result.assert_exit_code(
                    message=f"Couldn't set {vf_nic} {parameter} to {candidate}.",
                    include_output=True,
                )
            after_rejection = ethtool.get_device_coalesce_settings(
                vf_nic, force_run=True
            )
            assert_that(after_rejection.settings.get(parameter)).described_as(
                f"{vf_nic} {parameter} changed after rejecting candidate "
                f"{candidate}."
            ).is_equal_to(original_value)

        raise SkippedException(
            f"{vf_nic} accepted none of the alternate {parameter} values "
            f"{self.COALESCE_CANDIDATES}; there is no driver-independent way "
            "to infer another supported value."
        )

    def _reject_invalid_coalesce_value(
        self,
        ethtool: Ethtool,
        vf_nic: str,
        parameter: str,
        expected_value: int,
        log: Logger,
    ) -> None:
        log.info(
            f"Setting {vf_nic} {parameter} to {self.INVALID_COALESCE_VALUE}; "
            "the request is expected to fail."
        )
        invalid = ethtool.set_device_coalesce_setting(
            vf_nic, parameter, self.INVALID_COALESCE_VALUE
        )
        assert_that(invalid.exit_code).described_as(
            f"{vf_nic} accepted {parameter}={self.INVALID_COALESCE_VALUE}, which "
            "is outside the parameter's u32 range."
        ).is_not_equal_to(0)

        after_invalid = ethtool.get_device_coalesce_settings(vf_nic, force_run=True)
        assert_that(after_invalid.settings[parameter]).described_as(
            f"{vf_nic} {parameter} changed after a rejected request."
        ).is_equal_to(expected_value)

    @TestCaseMetadata(
        description="""
        This case verifies the SR-IOV VF driver reports and applies its combined
        channel count correctly.

        Channel count controls how many queue pairs the NIC uses and how work
        spreads across CPUs. Changing it rebuilds the datapath, so it must leave
        a working interface behind.

        Steps,
        1. Get the VF interface and read its channel configuration.
        2. Verify the effective maximum is non-zero and the current count does
           not exceed it.
        3. Set every combined channel count from one through the effective
           maximum and verify each value is applied.
        4. Verify the interface still passes traffic.
        5. Restore the original channel count and verify it is applied.

        This test is generated by the lisa_test_writer prompt.
        """,
        priority=2,
        maturity="preview",
        requirement=simple_requirement(
            min_count=2,
            network_interface=features.Sriov(),
            unsupported_os=[BSD, Windows],
        ),
        tags=["ai-generated"],
    )
    def verify_sriov_ethtool_channels(
        self, environment: Environment, log: Logger
    ) -> None:
        node = cast(RemoteNode, environment.nodes[0])
        ethtool = node.tools[Ethtool]

        vf_nics = self._get_vf_nics(node, log, "channel configuration")

        original_counts: Dict[str, int] = {}
        restoration_failures: List[str] = []
        try:
            for vf_nic in vf_nics:
                try:
                    original = ethtool.get_device_channels_info(vf_nic, force_run=True)
                except UnsupportedOperationException as identifier:
                    raise SkippedException(identifier) from identifier

                # Schedule the restore before changing the device. A command
                # can succeed while its readback assertion fails.
                original_counts[vf_nic] = original.current_channels
                self._verify_vf_channel_counts(
                    ethtool,
                    vf_nic,
                    original.current_channels,
                    original.max_channels,
                    log,
                )
            # The rebuilt datapath has to keep carrying traffic on every VF.
            vm_nics = initialize_nic_info(environment)
            sriov_vf_connection_test(environment, vm_nics)
        finally:
            for vf_nic, original_count in original_counts.items():
                try:
                    restored = ethtool.change_device_channels_info(
                        vf_nic, original_count
                    )
                    if restored.current_channels != original_count:
                        message = (
                            f"{vf_nic} combined channel count was not restored "
                            f"to its original value {original_count}; the driver "
                            f"reported {restored.current_channels}. Inspect the "
                            "driver and ethtool output."
                        )
                        log.error(message)
                        restoration_failures.append(message)
                except LisaException as identifier:
                    message = (
                        f"Failed to restore {vf_nic} combined channel count to "
                        f"{original_count}: {identifier}. Inspect the driver and "
                        "ethtool output."
                    )
                    log.error(message)
                    restoration_failures.append(message)

        assert_that(restoration_failures).described_as(
            "One or more SR-IOV VFs retained a modified channel count after "
            "all restoration attempts."
        ).is_empty()
        log.info(f"Channel configuration of {vf_nics} validated and restored.")

    def _verify_vf_channel_counts(
        self,
        ethtool: Ethtool,
        vf_nic: str,
        current: int,
        effective_maximum: int,
        log: Logger,
    ) -> None:
        # Ethtool caps max_channels at the node's vCPU count, so it is an
        # effective ceiling rather than the driver's raw advertised maximum.
        log.debug(
            f"{vf_nic} combined channels current/effective maximum: "
            f"{current}/{effective_maximum}"
        )

        assert_that(effective_maximum).described_as(
            f"{vf_nic} reported a zero effective maximum combined channel "
            "count, so the VF driver does not expose a tunable channel count."
        ).is_greater_than(0)
        assert_that(current).described_as(
            f"{vf_nic} current combined channel count exceeds the vCPU-capped "
            "effective maximum."
        ).is_less_than_or_equal_to(effective_maximum)

        if effective_maximum <= 1:
            raise SkippedException(
                f"{vf_nic} has an effective maximum of {effective_maximum} "
                "combined channel, so there is no alternate count to validate."
            )

        for new_channels in range(1, effective_maximum + 1):
            log.info(f"Setting {vf_nic} combined channels to {new_channels}")
            changed = ethtool.change_device_channels_info(vf_nic, new_channels)
            assert_that(changed.current_channels).described_as(
                f"{vf_nic} did not apply combined channel count {new_channels}."
            ).is_equal_to(new_channels)

    @TestCaseMetadata(
        description="""
        This case verifies the SR-IOV VF driver reports per-queue statistics
        correctly.

        Driver statistics are the first thing checked when diagnosing packet
        loss or throughput problems, so the counter set must be complete,
        consistently named, and must advance by the known packet count when
        controlled traffic flows through the VF.

        Steps,
        1. Read statistics from every VF interface.
        2. Verify that every statistic has a name and value, and that RX and TX
           per-queue packet counters are present.
        3. Record a baseline snapshot of the counters.
        4. Send 1,000 successful echo requests and replies through each VF.
        5. Verify the packet counters advance beyond background traffic.

        This test is generated by the lisa_test_writer prompt.
        """,
        priority=2,
        maturity="preview",
        requirement=simple_requirement(
            min_count=2,
            network_interface=features.Sriov(),
            unsupported_os=[BSD, Windows],
        ),
        tags=["ai-generated"],
    )
    def verify_sriov_ethtool_statistics(
        self, environment: Environment, log: Logger
    ) -> None:
        node = cast(RemoteNode, environment.nodes[0])
        ethtool = node.tools[Ethtool]

        vf_nics = self._get_vf_nics(node, log, "device statistics")
        baselines = {
            vf_nic: self._verify_vf_statistics_shape(ethtool, vf_nic, log)
            for vf_nic in vf_nics
        }

        vm_nics = initialize_nic_info(environment)
        for vf_nic in vf_nics:
            self._send_vf_statistics_traffic(environment, vm_nics, vf_nic)

        for vf_nic, baseline in baselines.items():
            self._verify_vf_statistics_advanced(ethtool, vf_nic, baseline, log)

    def _send_vf_statistics_traffic(
        self,
        environment: Environment,
        vm_nics: Dict[str, Dict[str, NicInfo]],
        vf_nic: str,
    ) -> None:
        source_node = cast(RemoteNode, environment.nodes[0])
        destination_node = cast(RemoteNode, environment.nodes[1])
        source_info = next(
            (
                nic
                for nic in vm_nics[source_node.name].values()
                if nic.pci_device_name == vf_nic and nic.ip_addr
            ),
            None,
        )
        assert_that(source_info).described_as(
            f"No IP-bearing synthetic interface is paired with VF {vf_nic} "
            f"on {source_node.name}. Inspect the Accelerated Networking pairing."
        ).is_not_none()
        source_info = cast(NicInfo, source_info)

        # Azure test networks use an IPv4 /24 for each primary NIC subnet.
        source_subnet = source_info.ip_addr.rsplit(".", maxsplit=1)[0]
        destination_info = next(
            (
                nic
                for nic in vm_nics[destination_node.name].values()
                if not nic.is_infiniband
                and nic.ip_addr
                and nic.ip_addr.rsplit(".", maxsplit=1)[0] == source_subnet
            ),
            None,
        )
        assert_that(destination_info).described_as(
            f"No destination interface on {destination_node.name} shares the "
            f"subnet of {source_info.ip_addr}. Inspect the test network topology."
        ).is_not_none()
        destination_info = cast(NicInfo, destination_info)

        source_node.tools[Ping].ping(
            target=destination_info.ip_addr,
            nic_name=source_info.name,
            count=self._STATISTICS_PING_COUNT,
            # A short interval keeps 1,000 controlled packets bounded to about
            # ten seconds while sudo permits Linux intervals below 200 ms.
            interval=0.01,
            # Stay below the standard Ethernet MTU while exercising non-trivial
            # payload accounting on every request and reply.
            package_size=1400,
            sudo=True,
        )

    def _verify_vf_statistics_shape(
        self, ethtool: Ethtool, vf_nic: str, log: Logger
    ) -> Dict[str, int]:
        try:
            statistics = ethtool.get_device_statistics(vf_nic, force_run=True)
        except UnsupportedOperationException as identifier:
            raise SkippedException(identifier) from identifier

        # A driver whose ETH_SS_STATS string table is shorter than the value
        # array it reports prints trailing entries with an empty name. Those
        # all parse to the same empty key, so they collapse into a single
        # counter and have to be counted in the raw output instead. This is
        # checked first because shifted names would misattribute later deltas.
        unnamed = self._count_unnamed_counters(statistics.raw_output)
        assert_that(unnamed).described_as(
            f"{vf_nic} printed {unnamed} statistics with an empty name, so the "
            "VF driver's ethtool string table is shorter than the value array "
            "it reports. Inspect the driver string and statistics tables."
        ).is_equal_to(0)

        counters = {name: value for name, value in statistics.counters.items() if name}
        assert_that(counters).described_as(
            f"{vf_nic} reported no statistics. Verify the VF driver implements "
            "ethtool statistics and inspect the ethtool output."
        ).is_not_empty()

        valueless = self._get_valueless_counters(statistics.raw_output, counters)
        assert_that(valueless).described_as(
            f"{vf_nic} reported statistics without a readable value: {valueless}. "
            "Inspect the driver statistics output and string table."
        ).is_empty()

        rx_per_queue = [
            name
            for name in counters
            if self._RX_QUEUE_PACKET_COUNTER_PATTERN.search(name)
        ]
        tx_per_queue = [
            name
            for name in counters
            if self._TX_QUEUE_PACKET_COUNTER_PATTERN.search(name)
        ]
        assert_that(rx_per_queue).described_as(
            f"{vf_nic} reported no RX per-queue packet counters. Verify the VF "
            "driver exposes queue statistics for receive-path diagnosis."
        ).is_not_empty()
        assert_that(tx_per_queue).described_as(
            f"{vf_nic} reported no TX per-queue packet counters. Verify the VF "
            "driver exposes queue statistics for transmit-path diagnosis."
        ).is_not_empty()

        log.debug(
            f"{vf_nic} exposes {len(counters)} counters, including "
            f"{len(rx_per_queue)} RX and {len(tx_per_queue)} TX queue packet "
            "counters"
        )
        return dict(counters)

    def _count_unnamed_counters(self, raw_output: str) -> int:
        unnamed = 0
        for line in raw_output.splitlines():
            stripped = line.strip()
            if not stripped or stripped == "NIC statistics:":
                continue
            name, separator, _ = stripped.partition(":")
            if separator and not name.strip():
                unnamed += 1
        return unnamed

    def _get_valueless_counters(
        self, raw_output: str, counters: Dict[str, int]
    ) -> List[str]:
        valueless: List[str] = []
        for line in raw_output.splitlines():
            stripped = line.strip()
            if not stripped or stripped == "NIC statistics:":
                continue
            name, separator, _ = stripped.partition(":")
            if separator and name.strip() not in counters:
                valueless.append(stripped)
        return valueless

    def _verify_vf_statistics_advanced(
        self,
        ethtool: Ethtool,
        vf_nic: str,
        baseline: Dict[str, int],
        log: Logger,
    ) -> None:
        delta = ethtool.get_device_statistics_delta(vf_nic, baseline)
        rx_delta = sum(
            value
            for name, value in delta.items()
            if self._RX_QUEUE_PACKET_COUNTER_PATTERN.search(name)
        )
        tx_delta = sum(
            value
            for name, value in delta.items()
            if self._TX_QUEUE_PACKET_COUNTER_PATTERN.search(name)
        )
        log.debug(
            f"{vf_nic} per-queue packet counter delta RX/TX: " f"{rx_delta}/{tx_delta}"
        )

        assert_that(rx_delta).described_as(
            f"{vf_nic} RX per-queue packet counters advanced by only {rx_delta} "
            f"after {self._STATISTICS_PING_COUNT} successful echo replies. Verify "
            "traffic traverses the VF and the driver accounts received packets."
        ).is_greater_than_or_equal_to(self._MINIMUM_STATISTICS_PACKET_DELTA)
        assert_that(tx_delta).described_as(
            f"{vf_nic} TX per-queue packet counters advanced by only {tx_delta} "
            f"after {self._STATISTICS_PING_COUNT} successful echo requests. Verify "
            "traffic traverses the VF and the driver accounts transmitted packets."
        ).is_greater_than_or_equal_to(self._MINIMUM_STATISTICS_PACKET_DELTA)
        log.info(f"Statistics of {vf_nic} validated after traffic.")

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
