# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from pathlib import Path
from typing import Any, Dict, List, cast

from assertpy import assert_that

from lisa import (
    Environment,
    Logger,
    Node,
    RemoteNode,
    TcpConnetionException,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    schema,
    search_space,
    simple_requirement,
)
from lisa.features import NetworkInterface, SerialConsole
from lisa.nic import NicInfo, Nics
from lisa.sut_orchestrator import AZURE, READY
from lisa.tools import Cat, Ethtool, Firewall, Iperf3, Kill, Lsmod, Lspci, Modprobe, Ssh
from lisa.util import SkippedException, constants
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
    # ConnectX-3 uses mlx4_core
    # mlx4_en and mlx4_ib depends on mlx4_core
    #  need remove mlx4_en and mlx4_ib firstly
    #  otherwise will see modules is in used issue
    # ConnectX-4/ConnectX-5 uses mlx5_core
    # mlx5_ib depends on mlx5_core, need remove mlx5_ib firstly
    reload_modules_dict: Dict[str, List[str]] = {
        "mlx5_core": ["mlx5_ib"],
        "mlx4_core": ["mlx4_en", "mlx4_ib"],
    }

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
            network_interface=schema.NetworkInterfaceOptionSettings(
                data_path=schema.NetworkDataPath.Sriov,
            ),
        ),
    )
    def sriov_basic_validation(self, environment: Environment) -> None:
        vm_nics = self._initialize_nic_info(environment)
        self._sriov_basic_test(environment, vm_nics)

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
            network_interface=schema.NetworkInterfaceOptionSettings(
                data_path=schema.NetworkDataPath.Sriov,
            ),
        ),
    )
    def sriov_single_vf_connection_validation(self, environment: Environment) -> None:
        vm_nics = self._initialize_nic_info(environment)
        self._sriov_basic_test(environment, vm_nics)
        self._sriov_vf_connection_test(environment, vm_nics)

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
            network_interface=schema.NetworkInterfaceOptionSettings(
                data_path=schema.NetworkDataPath.Sriov,
            ),
        ),
    )
    def sriov_single_vf_connection_max_cpu_validation(
        self, environment: Environment
    ) -> None:
        vm_nics = self._initialize_nic_info(environment)
        self._sriov_basic_test(environment, vm_nics)
        self._sriov_vf_connection_test(environment, vm_nics)

    @TestCaseMetadata(
        description="""
        This case needs 2 nodes and 8 nics. And it verifies module of sriov network
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
                nic_count=8,
                data_path=schema.NetworkDataPath.Sriov,
            ),
        ),
    )
    def sriov_max_vf_connection_validation(self, environment: Environment) -> None:
        vm_nics = self._initialize_nic_info(environment)
        self._sriov_basic_test(environment, vm_nics)
        self._sriov_vf_connection_test(environment, vm_nics)

    @TestCaseMetadata(
        description="""
        This case needs 2 nodes, 8 nics and 64 Vcpus. And it verifies module of sriov
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
                nic_count=8,
                data_path=schema.NetworkDataPath.Sriov,
            ),
        ),
    )
    def sriov_max_vf_connection_max_cpu_validation(
        self, environment: Environment
    ) -> None:
        vm_nics = self._initialize_nic_info(environment)
        self._sriov_basic_test(environment, vm_nics)
        self._sriov_vf_connection_test(environment, vm_nics)

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
        vm_nics = self._initialize_nic_info(environment)
        self._sriov_basic_test(environment, vm_nics)
        node = cast(RemoteNode, environment.nodes[0])
        network_interface_feature = node.features[NetworkInterface]
        for _ in range(3):
            sriov_is_enabled = network_interface_feature.is_enabled_sriov()
            if sriov_is_enabled:
                self._sriov_basic_test(environment, vm_nics)
            network_interface_feature._switch_sriov(enable=(not sriov_is_enabled))
        network_interface_feature._switch_sriov(enable=True)

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
        vm_nics = self._initialize_nic_info(environment)
        self._sriov_basic_test(environment, vm_nics)
        self._sriov_vf_connection_test(environment, vm_nics)

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
        vm_nics = self._initialize_nic_info(environment)
        self._sriov_basic_test(environment, vm_nics)
        self._sriov_vf_connection_test(environment, vm_nics, turn_off_vf=True)

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
            vm_nics = self._initialize_nic_info(environment)
            self._sriov_basic_test(environment, vm_nics)
        else:
            serial_console = node.features[SerialConsole]
            serial_console.check_panic(saved_path=log_path, stage="after_attach_nics")
            raise TcpConnetionException(
                node.public_address,
                node.public_port,
                tcp_error_code,
                "no panic found in serial log after attach nics",
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
        vm_nics = self._initialize_nic_info(environment)
        self._sriov_basic_test(environment, vm_nics)

    @TestCaseMetadata(
        description="""
        This case verify VM works well during remove and load sriov modules.

        Steps,
        1. Provision VM with max network interfaces with enabling accelerated network.
        2. Do the basic sriov testing.
        3. Remove sriov module, check network traffic through synthetic nic.
        4. Load sriov module, check network traffic through VF.
        """,
        priority=2,
        requirement=simple_requirement(
            min_count=2,
            min_nic_count=8,
            network_interface=schema.NetworkInterfaceOptionSettings(
                data_path=schema.NetworkDataPath.Sriov,
            ),
        ),
    )
    def sriov_reload_modules_validation(self, environment: Environment) -> None:
        vm_nics = self._initialize_nic_info(environment)
        self._sriov_basic_test(environment, vm_nics)
        module_in_used = ""
        for node in environment.nodes.list():
            module_in_used = self._remove_module(node)
        self._sriov_vf_connection_test(environment, vm_nics, remove_module=True)
        for node in environment.nodes.list():
            self._load_module(node, module_in_used)
        vm_nics = self._initialize_nic_info(environment)
        self._sriov_vf_connection_test(environment, vm_nics)

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
                nic_count=search_space.IntRange(min=3, max=8),
                data_path=schema.NetworkDataPath.Sriov,
            ),
        ),
    )
    def sriov_ethtool_offload_setting(self, environment: Environment) -> None:
        client_iperf3_log = "iperfResults.log"
        server_node = cast(RemoteNode, environment.nodes[0])
        client_node = cast(RemoteNode, environment.nodes[1])
        client_ethtool = client_node.tools[Ethtool]
        vm_nics = self._initialize_nic_info(environment)
        # skip test if scatter-gather can't be updated
        for _, client_nic_info in vm_nics[client_node.name].items():
            device_sg_settings = client_ethtool.get_device_sg_settings(
                client_nic_info.upper, True
            )
            if device_sg_settings.sg_fixed:
                raise SkippedException(
                    "scatter-gather is fixed can cannot be changed for device"
                    f" {client_nic_info.upper}. Skipping test."
                )
            else:
                break
        # save original enabled features
        device_enabled_features_origin = client_ethtool.get_all_device_enabled_features(
            True
        )

        # preparation work before launch iperf3
        self._stop_firewall(environment)

        # run iperf3 on server side and client side
        # iperfResults.log stored client side log
        source_iperf3 = server_node.tools[Iperf3]
        dest_iperf3 = client_node.tools[Iperf3]
        source_iperf3.run_as_server()
        dest_iperf3.run_as_client_async(
            server_node.internal_address, client_iperf3_log, 1800
        )

        # wait for a while then check any error shown up in iperfResults.log
        dest_cat = client_node.tools[Cat]
        iperf_log = dest_cat.read_from_file(
            client_iperf3_log, sudo=True, force_run=True
        )
        assert_that(iperf_log).does_not_contain("error")

        # disable and enable VF in pci level
        for node in environment.nodes.list():
            lspci = node.tools[Lspci]
            lspci.disable_devices(constants.DEVICE_TYPE_SRIOV)
            lspci.enable_devices()
        # check VF still paired with synthetic nic
        vm_nics = self._initialize_nic_info(environment)

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
        for _, client_nic_info in vm_nics[client_node.name].items():
            new_settings = client_ethtool.change_device_sg_settings(
                client_nic_info.upper, True
            )
            device_vf_sg_settings = client_ethtool.get_device_sg_settings(
                client_nic_info.lower, True
            )
            assert_that(
                new_settings.sg_setting,
                "sg setting is not sync into VF.",
            ).is_equal_to(device_vf_sg_settings.sg_setting)

        # set off for scatter-gather feature for synthetic nic
        # verify vf scatter-gather feature has value 'off'
        for _, client_nic_info in vm_nics[client_node.name].items():
            new_settings = client_ethtool.change_device_sg_settings(
                client_nic_info.upper, False
            )
            device_vf_sg_settings = client_ethtool.get_device_sg_settings(
                client_nic_info.lower, True
            )
            assert_that(
                new_settings.sg_setting,
                "sg setting is not sync into VF.",
            ).is_equal_to(device_vf_sg_settings.sg_setting)

        #  disable and enable VF in pci level
        for node in environment.nodes.list():
            lspci = node.tools[Lspci]
            lspci.disable_devices(constants.DEVICE_TYPE_SRIOV)
            lspci.enable_devices()

        # check VF still paired with synthetic nic
        vm_nics = self._initialize_nic_info(environment)

        # check VF's scatter-gather feature keep consistent with previous status
        for _, client_nic_info in vm_nics[client_node.name].items():
            device_vf_sg_settings = client_ethtool.get_device_sg_settings(
                client_nic_info.lower, True
            )
            assert_that(
                device_vf_sg_settings.sg_setting,
                "sg setting is not sync into VF.",
            ).is_equal_to(False)

        # disable and enable sriov in network interface level
        network_interface_feature = client_node.features[NetworkInterface]
        for _ in range(3):
            sriov_is_enabled = network_interface_feature.is_enabled_sriov()
            network_interface_feature._switch_sriov(enable=(not sriov_is_enabled))
        network_interface_feature._switch_sriov(enable=True)

        # check VF still paired with synthetic nic
        vm_nics = self._initialize_nic_info(environment)

        # check VF's scatter-gather feature keep consistent with previous status
        for _, client_nic_info in vm_nics[client_node.name].items():
            device_vf_sg_settings = client_ethtool.get_device_sg_settings(
                client_nic_info.lower, True
            )
            assert_that(
                device_vf_sg_settings.sg_setting,
                "sg setting is not sync into VF.",
            ).is_equal_to(False)

        # reload sriov modules
        module_in_used = ""
        for node in environment.nodes.list():
            module_in_used = self._remove_module(node)
        for node in environment.nodes.list():
            self._load_module(node, module_in_used)

        # check VF still paired with synthetic nic
        vm_nics = self._initialize_nic_info(environment)

        # check VF's scatter-gather feature keep consistent with previous status
        for _, client_nic_info in vm_nics[client_node.name].items():
            device_vf_sg_settings = client_ethtool.get_device_sg_settings(
                client_nic_info.lower, True
            )
            assert_that(
                device_vf_sg_settings.sg_setting,
                "sg setting is not sync into VF.",
            ).is_equal_to(False)

        # check there is no error happen in iperf3 log
        # after above operations
        dest_cat = client_node.tools[Cat]
        iperf_log = dest_cat.read_from_file(
            client_iperf3_log, sudo=True, force_run=True
        )
        assert_that(iperf_log).does_not_contain("error")

    def after_case(self, log: Logger, **kwargs: Any) -> None:
        environment: Environment = kwargs.pop("environment")
        for node in environment.nodes.list():
            kill = node.tools[Kill]
            kill.by_name("iperf3")

    def _initialize_nic_info(
        self, environment: Environment
    ) -> Dict[str, Dict[str, NicInfo]]:
        vm_nics: Dict[str, Dict[str, NicInfo]] = {}
        for node in environment.nodes.list():
            node_nic_info = Nics(node)
            node_nic_info.initialize()
            for _, node_nic in node_nic_info.nics.items():
                assert_that(node_nic.lower).described_as(
                    f"This interface {node_nic.upper} does not have a paired VF."
                ).is_not_empty()
            vm_nics[node.name] = node_nic_info.nics
        return vm_nics

    def _remove_module(self, node: Node) -> str:
        lspci = node.tools[Lspci]
        modprobe = node.tools[Modprobe]
        devices_slots = lspci.get_devices_slots(
            constants.DEVICE_TYPE_SRIOV, force_run=True
        )
        # there will not be multiple Mellanox types in one VM
        # get the used module using any one of sriov device
        module_in_used = lspci.get_used_module(devices_slots[0])
        assert_that(self.reload_modules_dict).described_as(
            f"used modules {module_in_used} should be contained"
            f" in dict {self.reload_modules_dict}"
        ).contains(module_in_used)
        modprobe.remove(self.reload_modules_dict[module_in_used])
        return module_in_used

    def _load_module(self, node: Node, module_name: str) -> None:
        modprobe = node.tools[Modprobe]
        modprobe.load(module_name)

    def _get_packets(self, node: Node, nic_name: str, name: str = "tx_packets") -> int:
        cat = node.tools[Cat]
        return int(
            cat.read_from_file(
                f"/sys/class/net/{nic_name}/statistics/{name}", force_run=True
            )
        )

    def _sriov_basic_test(
        self, environment: Environment, vm_nics: Dict[str, Dict[str, NicInfo]]
    ) -> None:
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

            # 2. Check VF counts listed from lspci is expected.
            lspci = node.tools[Lspci]
            devices_slots = lspci.get_devices_slots(
                constants.DEVICE_TYPE_SRIOV, force_run=True
            )
            assert_that(devices_slots).described_as(
                "count of sriov devices listed from lspci is not expected,"
                " please check the driver works properly"
            ).is_length(len(vm_nics[node.name]))

    def _sriov_vf_connection_test(
        self,
        environment: Environment,
        vm_nics: Dict[str, Dict[str, NicInfo]],
        turn_off_vf: bool = False,
        remove_module: bool = False,
    ) -> None:
        source_node = cast(RemoteNode, environment.nodes[0])
        dest_node = cast(RemoteNode, environment.nodes[1])
        source_ssh = source_node.tools[Ssh]
        dest_ssh = dest_node.tools[Ssh]

        dest_ssh.enable_public_key(source_ssh.generate_key_pairs())
        # generate 200Mb file
        source_node.execute("dd if=/dev/urandom of=large_file bs=100 count=0 seek=2M")
        max_retry_times = 10
        for _, source_nic_info in vm_nics[source_node.name].items():
            matched_dest_nic_name = ""
            for dest_nic_name, dest_nic_info in vm_nics[dest_node.name].items():
                # only when IPs are in the same subnet, IP1 of machine A can connect to
                # IP2 of machine B
                # e.g. eth2 IP is 10.0.2.3 on machine A, eth2 IP is 10.0.3.4 on machine
                # B, use nic name doesn't work in this situation
                if (
                    dest_nic_info.ip_addr.rsplit(".", maxsplit=1)[0]
                    == source_nic_info.ip_addr.rsplit(".", maxsplit=1)[0]
                ):
                    matched_dest_nic_name = dest_nic_name
                    break
            assert_that(matched_dest_nic_name).described_as(
                f"can't find the same subnet nic with {source_nic_info.ip_addr} on"
                f" machine {source_node.name}, please check network setting of "
                f"machine {dest_node.name}."
            ).is_not_empty()
            desc_nic_info = vm_nics[dest_node.name][matched_dest_nic_name]
            dest_ip = vm_nics[dest_node.name][matched_dest_nic_name].ip_addr
            source_ip = source_nic_info.ip_addr
            source_synthetic_nic = source_nic_info.upper
            dest_synthetic_nic = desc_nic_info.upper
            source_nic = source_vf_nic = source_nic_info.lower
            dest_nic = dest_vf_nic = desc_nic_info.lower

            if remove_module or turn_off_vf:
                source_nic = source_synthetic_nic
                dest_nic = dest_synthetic_nic
            if turn_off_vf:
                source_node.execute(f"ip link set dev {source_vf_nic} down", sudo=True)
                dest_node.execute(f"ip link set dev {dest_vf_nic} down", sudo=True)

            # get origin tx_packets and rx_packets before copy file
            source_tx_packets_origin = self._get_packets(source_node, source_nic)
            dest_tx_packets_origin = self._get_packets(
                dest_node, dest_nic, "rx_packets"
            )

            # check the connectivity between source and dest machine using ping
            for _ in range(max_retry_times):
                cmd_result = source_node.execute(
                    f"ping -c 1 {dest_ip} -I {source_synthetic_nic}"
                )
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
            source_tx_packets = self._get_packets(source_node, source_nic)
            dest_tx_packets = self._get_packets(dest_node, dest_nic, "rx_packets")
            # verify tx_packets value of source nic is increased after coping 200Mb file
            #  from source to dest
            assert_that(
                int(source_tx_packets), "insufficient TX packets sent"
            ).is_greater_than(int(source_tx_packets_origin))
            # verify rx_packets value of dest nic is increased after receiving 200Mb
            #  file from source to dest
            assert_that(
                int(dest_tx_packets), "insufficient RX packets received"
            ).is_greater_than(int(dest_tx_packets_origin))

            if turn_off_vf:
                source_node.execute(f"ip link set dev {source_vf_nic} up", sudo=True)
                dest_node.execute(f"ip link set dev {dest_vf_nic} up", sudo=True)

    def _stop_firewall(self, environment: Environment) -> None:
        for node in environment.nodes.list():
            firewall = node.tools[Firewall]
            firewall.stop()
