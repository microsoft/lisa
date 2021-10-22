# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from pathlib import Path
from typing import Dict, cast

from assertpy import assert_that

from lisa import (
    Environment,
    Logger,
    RemoteNode,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    schema,
    simple_requirement,
)
from lisa.features import NetworkInterface, SerialConsole
from lisa.nic import NicInfo, Nics
from lisa.sut_orchestrator import AZURE, READY
from lisa.tools import Cat, Lsmod, Lspci, Ssh
from lisa.util import LisaException, constants
from lisa.util.shell import wait_tcp_port_ready

vm_nics: Dict[str, Dict[str, NicInfo]] = {}


@TestSuiteMetadata(
    area="sriov",
    category="functional",
    description="""
    This test suite uses to verify accelerated network functionality.
    """,
)
class Sriov(TestSuite):
    TIME_OUT = 300

    @TestCaseMetadata(
        description="""
        This case verifies module of sriov network interface is loaded and each
         synthetic nic is paired with one VF.

        Steps,
        1. Check module of sriov network device is loaded.
        2. Check VF of synthetic nic is paired.
        3. Check VF counts listed from lspci is expected.
        """,
        priority=1,
        requirement=simple_requirement(
            network_interface=schema.NetworkInterfaceOptionSettings(
                data_path=schema.NetworkDataPath.Sriov,
            ),
        ),
    )
    def sriov_basic_validation(self, environment: Environment) -> None:
        self._sriov_basic_test(environment)

    @TestCaseMetadata(
        description="""
        This case verifies module of sriov network interface is loaded and
         each synthetic nic is paired with one VF, and check rx statistics of source
         and tx statistics of dest increase after send 200 Mb file from source to dest.

        Steps,
        1. Check module of sriov network device is loaded.
        2. Check VF of synthetic nic is paired.
        3. Check VF counts listed from lspci is expected.
        4. Setup SSH connection between source and dest with key authentication.
        5. Ping the dest IP from the source machine to check connectivity.
        6. Generate 200Mb file, copy from source to dest.
        7. Check rx statistics of source VF and tx statistics of dest VF is increased.
        """,
        priority=1,
        requirement=simple_requirement(
            min_count=2,
            network_interface=schema.NetworkInterfaceOptionSettings(
                data_path=schema.NetworkDataPath.Sriov,
            ),
        ),
    )
    def sriov_single_vf_connection_validation(self, environment: Environment) -> None:
        self._sriov_basic_test(environment)
        self._sriov_vf_connection_test(environment)

    @TestCaseMetadata(
        description="""
        This case needs 2 nodes and 64 Vcpus. And it verifies module of sriov network
         interface is loaded and each synthetic nic is paired with one VF, and check
         rx statistics of source and tx statistics of dest increase after send 200 Mb
         file from source to dest.

        Steps,
        1. Check module of sriov network device is loaded.
        2. Check VF of synthetic nic is paired.
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
            ),
        ),
    )
    def sriov_single_vf_connection_max_cpu_validation(
        self, environment: Environment
    ) -> None:
        self._sriov_basic_test(environment)
        self._sriov_vf_connection_test(environment)

    @TestCaseMetadata(
        description="""
        This case needs 2 nodes and 8 nics. And it verifies module of sriov network
         interface is loaded and each synthetic nic is paired with one VF, and check
         rx statistics of source and tx statistics of dest increase after send 200 Mb
         file from source to dest.

        Steps,
        1. Check module of sriov network device is loaded.
        2. Check VF of synthetic nic is paired.
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
                nic_count=8,
                data_path=schema.NetworkDataPath.Sriov,
            ),
        ),
    )
    def sriov_max_vf_connection_validation(self, environment: Environment) -> None:
        self._sriov_basic_test(environment)
        self._sriov_vf_connection_test(environment)

    @TestCaseMetadata(
        description="""
        This case needs 2 nodes, 8 nics and 64 Vcpus. And it verifies module of sriov
         network interface is loaded and each synthetic nic is paired with one VF, and
         check rx statistics of source and tx statistics of dest increase after send 200
         Mb file from source to dest.

        Steps,
        1. Check module of sriov network device is loaded.
        2. Check VF of synthetic nic is paired.
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
                nic_count=8,
                data_path=schema.NetworkDataPath.Sriov,
            ),
        ),
    )
    def sriov_max_vf_connection_max_cpu_validation(
        self, environment: Environment
    ) -> None:
        self._sriov_basic_test(environment)
        self._sriov_vf_connection_test(environment)

    @TestCaseMetadata(
        description="""
        This case verify VM works well after disable and enable accelerated network in
         network interface through sdk.

        Steps,
        1. Do the basic sriov check.
        2. Set enable_accelerated_networking as False to disable sriov.
        3. Set enable_accelerated_networking as True to enable sriov.
        4. Do the basic sriov check.
        """,
        priority=2,
        requirement=simple_requirement(
            network_interface=schema.NetworkInterfaceOptionSettings(
                data_path=schema.NetworkDataPath.Sriov,
            ),
            supported_platform_type=[AZURE, READY],
        ),
    )
    def sriov_disable_enable_validation(self, environment: Environment) -> None:
        self._sriov_basic_test(environment)
        node = cast(RemoteNode, environment.nodes[0])
        network_interface_feature = node.features[NetworkInterface]
        for _ in range(3):
            sriov_is_enabled = network_interface_feature.is_enabled_sriov()
            if sriov_is_enabled:
                self._sriov_basic_test(environment)
            network_interface_feature._switch_sriov(enable=(not sriov_is_enabled))

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
            network_interface=schema.NetworkInterfaceOptionSettings(
                data_path=schema.NetworkDataPath.Sriov,
            ),
        ),
    )
    def sriov_disable_enable_pci_validation(self, environment: Environment) -> None:
        for node in environment.nodes.list():
            lspci = node.tools[Lspci]
            lspci.disable_devices(constants.DEVICE_TYPE_SRIOV)
            lspci.enable_devices()
        self._sriov_basic_test(environment)
        self._sriov_vf_connection_test(environment)

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
            network_interface=schema.NetworkInterfaceOptionSettings(
                data_path=schema.NetworkDataPath.Sriov,
            ),
        ),
    )
    def sriov_disable_enable_on_guest_validation(
        self, environment: Environment
    ) -> None:
        self._sriov_basic_test(environment)
        self._sriov_vf_connection_test(environment, turn_off_vf=True)

    @TestCaseMetadata(
        description="""
        This case verify VM works well after attached the max sriov nics after
         provision.

        Steps,
        1. Attach 7 extra sriov nic into the VM.
        2. Do the basic sriov testing.
        """,
        priority=2,
        requirement=simple_requirement(
            network_interface=schema.NetworkInterfaceOptionSettings(
                data_path=schema.NetworkDataPath.Sriov,
                max_nic_count=8,
            ),
        ),
    )
    def sriov_add_max_nics_validation(
        self, log_path: Path, log: Logger, environment: Environment
    ) -> None:
        node = cast(RemoteNode, environment.nodes[0])
        network_interface_feature = node.features[NetworkInterface]
        network_interface_feature.attach_nics(extra_nic_count=7)
        is_ready, tcp_error_code = wait_tcp_port_ready(
            node.public_address, node.public_port, log=log, timeout=self.TIME_OUT
        )
        if is_ready:
            self._sriov_basic_test(environment)
        else:
            serial_console = node.features[SerialConsole]
            serial_console.check_panic(saved_path=log_path, stage="after_attach_nics")
            raise LisaException(
                f"Cannot connect to [{node.public_address}:{node.public_port}], "
                f"error code: {tcp_error_code}, no panic found in serial log"
            )

    @TestCaseMetadata(
        description="""
        This case verify VM works well when provison with max (8) sriov nics.

        Steps,
        1. Provision VM with max network interfaces with enabling accelerated network.
        2. Do the basic sriov testing.
        """,
        priority=2,
        requirement=simple_requirement(
            min_nic_count=8,
            network_interface=schema.NetworkInterfaceOptionSettings(
                data_path=schema.NetworkDataPath.Sriov,
            ),
        ),
    )
    def sriov_provision_with_max_nics_validation(
        self, environment: Environment
    ) -> None:
        self._sriov_basic_test(environment)

    def _sriov_basic_test(self, environment: Environment) -> None:
        for node in environment.nodes.list():
            # 1. Check module of sriov network device is loaded.
            modules_exist = False
            lsmod = node.tools[Lsmod]
            for module in ["mlx4_core", "mlx4_en", "mlx5_core", "ixgbevf"]:
                if lsmod.module_exists(module):
                    modules_exist = True
            assert_that(modules_exist).described_as(
                "The module of sriov network device isn't loaded."
            ).is_true()

            # 2. Check VF of synthetic nic is paired.
            node_nic_info = Nics(node)
            node_nic_info.initialize()
            for _, node_nic in node_nic_info._nics.items():
                assert_that(node_nic.lower).described_as(
                    f"This interface {node_nic.upper} does not have a paired VF."
                ).is_not_equal_to("")
            vm_nics[node.name] = node_nic_info._nics
            # 3. Check VF counts listed from lspci is expected.
            lspci = node.tools[Lspci]
            devices_slots = lspci.get_devices_slots(
                constants.DEVICE_TYPE_SRIOV, force_run=True
            )
            assert_that(devices_slots).described_as(
                "count of sriov devices listed from lspci is not expected,"
                " please check the driver works properly"
            ).is_length(len(node_nic_info))

    def _sriov_vf_connection_test(
        self, environment: Environment, turn_off_vf: bool = False
    ) -> None:
        source_node = cast(RemoteNode, environment.nodes[0])
        dest_node = cast(RemoteNode, environment.nodes[1])
        dest_cat = dest_node.tools[Cat]
        source_cat = source_node.tools[Cat]
        source_ssh = source_node.tools[Ssh]
        dest_ssh = dest_node.tools[Ssh]

        dest_ssh.enable_public_key(source_ssh.generate_key_pairs())
        # generate 200Mb file
        source_node.execute("dd if=/dev/urandom of=large_file bs=100 count=0 seek=2M")
        max_retry_times = 10
        for source_nic_name, source_nic_info in vm_nics[source_node.name].items():
            desc_nic_info = vm_nics[dest_node.name][source_nic_name]
            dest_ip = vm_nics[dest_node.name][source_nic_name].ip_addr
            source_ip = source_nic_info.ip_addr
            source_synthetic_nic = source_nic_info.upper
            dest_synthetic_nic = desc_nic_info.upper
            source_nic = source_vf_nic = source_nic_info.lower
            dest_nic = dest_vf_nic = desc_nic_info.lower

            if turn_off_vf:
                source_node.execute(f"ip link set dev {source_vf_nic} down", sudo=True)
                dest_node.execute(f"ip link set dev {dest_vf_nic} down", sudo=True)
                source_nic = source_synthetic_nic
                dest_nic = dest_synthetic_nic

            # get origin tx_packets and rx_packets before copy file
            source_tx_packets_origin = source_cat.read_from_file(
                f"/sys/class/net/{source_nic}/statistics/tx_packets"
            )
            dest_tx_packets_origin = dest_cat.read_from_file(
                f"/sys/class/net/{dest_nic}/statistics/rx_packets"
            )

            # check the connectivity between source and dest machine using ping
            for _ in range(max_retry_times):
                cmd_result = source_node.execute(f"ping -c 1 {dest_ip}")
                if cmd_result.exit_code == 0:
                    break
            cmd_result.assert_exit_code(
                message=f"fail to ping {dest_ip} from {source_node.name} to "
                f"{dest_node.name} after retry {max_retry_times}"
            )

            # copy 200 Mb file from source ip to dest ip
            cmd_result = source_node.execute(
                f"scp -o BindAddress={source_ip} -i ~/.ssh/id_rsa -o"
                f" StrictHostKeyChecking=no large_file "
                f"$USER@{dest_ip}:/tmp/large_file",
                shell=True,
                expected_exit_code=0,
                expected_exit_code_failure_message="Fail to copy file large_file from"
                f" {source_ip} to {dest_ip}",
            )

            # verify tx_packets value of source nic is increased after coping 200Mb file
            #  from source to dest
            source_tx_packets = source_cat.read_from_file(
                f"/sys/class/net/{source_nic}/statistics/tx_packets", force_run=True
            )
            assert_that(
                int(source_tx_packets), "insufficient TX packets sent"
            ).is_greater_than(int(source_tx_packets_origin))
            # verify rx_packets value of dest nic is increased after receiving 200Mb
            #  file from source to dest
            dest_tx_packets = dest_cat.read_from_file(
                f"/sys/class/net/{dest_nic}/statistics/rx_packets", force_run=True
            )
            assert_that(
                int(dest_tx_packets), "insufficient RX packets received"
            ).is_greater_than(int(dest_tx_packets_origin))
            if turn_off_vf:
                source_node.execute(f"ip link set dev {source_vf_nic} up", sudo=True)
                dest_node.execute(f"ip link set dev {dest_vf_nic} up", sudo=True)
