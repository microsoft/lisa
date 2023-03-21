# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from pathlib import Path
from typing import Any, Dict, cast

from assertpy import assert_that

from lisa import (
    Environment,
    Logger,
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
from lisa.sut_orchestrator import AZURE
from lisa.tools import (
    Cat,
    Ethtool,
    Firewall,
    InterruptInspector,
    Iperf3,
    KernelConfig,
    Lscpu,
    Lspci,
)
from lisa.util import UnsupportedDistroException
from lisa.util.shell import wait_tcp_port_ready
from microsoft.testsuites.network.common import (
    cleanup_iperf3,
    get_used_config,
    initialize_nic_info,
    load_module,
    remove_extra_nics,
    remove_module,
    restore_extra_nics,
    sriov_basic_test,
    sriov_disable_enable,
    sriov_vf_connection_test,
)


@TestSuiteMetadata(
    area="sriov",
    category="functional",
    description="""
    This test suite uses to verify accelerated network functionality.
    """,
)
class Sriov(TestSuite):
    TIME_OUT = 300

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
    def verify_services_state(self, environment: Environment) -> None:
        try:
            for node in environment.nodes.list():
                assert_that(node.tools[Systemctl].state()).is_equal_to("running")
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
    def sriov_basic_validation(self, environment: Environment) -> None:
        vm_nics = initialize_nic_info(environment)
        sriov_basic_test(environment, vm_nics)

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
        sriov_basic_test(environment, vm_nics)
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
        sriov_basic_test(environment, vm_nics)
        sriov_vf_connection_test(environment, vm_nics)

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
    def verify_sriov_max_vf_connection(self, environment: Environment) -> None:
        vm_nics = initialize_nic_info(environment)
        sriov_basic_test(environment, vm_nics)
        sriov_vf_connection_test(environment, vm_nics)

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
    def verify_sriov_max_vf_connection_max_cpu(self, environment: Environment) -> None:
        vm_nics = initialize_nic_info(environment)
        sriov_basic_test(environment, vm_nics)
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
        priority=2,
        requirement=simple_requirement(
            network_interface=features.Sriov(),
            supported_platform_type=[AZURE],
        ),
    )
    def verify_sriov_disable_enable(self, environment: Environment) -> None:
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
        for node in environment.nodes.list():
            lspci = node.tools[Lspci]
            lspci.disable_devices_by_type(constants.DEVICE_TYPE_SRIOV)
            lspci.enable_devices()
        vm_nics = initialize_nic_info(environment)
        sriov_basic_test(environment, vm_nics)
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
        vm_nics = initialize_nic_info(environment)
        sriov_basic_test(environment, vm_nics)
        sriov_vf_connection_test(environment, vm_nics, turn_off_vf=True)

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
                max_nic_count=8,
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
                node.public_address, node.public_port, log=log, timeout=self.TIME_OUT
            )
            if is_ready:
                vm_nics = initialize_nic_info(environment)
                sriov_basic_test(environment, vm_nics)
            else:
                serial_console = node.features[SerialConsole]
                serial_console.check_panic(
                    saved_path=log_path, stage="after_attach_nics"
                )
                raise TcpConnectionException(
                    node.public_address,
                    node.public_port,
                    tcp_error_code,
                    "no panic found in serial log after attach nics",
                )
        finally:
            restore_extra_nics(environment)

    @TestCaseMetadata(
        description="""
        This case verify VM works well when provisioning with max (8) sriov nics.

        Steps,
        1. Provision VM with max network interfaces with enabling accelerated network.
        2. Do the basic sriov testing.
        """,
        priority=2,
        requirement=simple_requirement(
            min_nic_count=8,
            network_interface=features.Sriov(),
        ),
    )
    def verify_sriov_provision_with_max_nics(self, environment: Environment) -> None:
        vm_nics = initialize_nic_info(environment)
        sriov_basic_test(environment, vm_nics)

    @TestCaseMetadata(
        description="""
        This case verify VM works well when provisioning with max (8) sriov nics.

        Steps,
        1. Provision VM with max network interfaces with enabling accelerated network.
        2. Do the basic sriov testing.
        3. Reboot VM from guest.
        4. Do the basic sriov testing.
        """,
        priority=2,
        requirement=simple_requirement(
            min_nic_count=8,
            network_interface=features.Sriov(),
        ),
    )
    def verify_sriov_provision_with_max_nics_reboot(
        self, environment: Environment
    ) -> None:
        vm_nics = initialize_nic_info(environment)
        sriov_basic_test(environment, vm_nics)
        for node in environment.nodes.list():
            node.reboot()
        sriov_basic_test(environment, vm_nics)

    @TestCaseMetadata(
        description="""
        This case verify VM works well when provisioning with max (8) sriov nics.

        Steps,
        1. Provision VM with max network interfaces with enabling accelerated network.
        2. Do the basic sriov testing.
        3. Reboot VM from API.
        4. Do the basic sriov testing.
        """,
        priority=2,
        requirement=simple_requirement(
            min_nic_count=8,
            network_interface=features.Sriov(),
        ),
    )
    def verify_sriov_provision_with_max_nics_reboot_from_platform(
        self, environment: Environment
    ) -> None:
        vm_nics = initialize_nic_info(environment)
        sriov_basic_test(environment, vm_nics)
        for node in environment.nodes.list():
            start_stop = node.features[StartStop]
            start_stop.restart()
        sriov_basic_test(environment, vm_nics)

    @TestCaseMetadata(
        description="""
        This case verify VM works well when provisioning with max (8) sriov nics.

        Steps,
        1. Provision VM with max network interfaces with enabling accelerated network.
        2. Do the basic sriov testing.
        3. Stop and Start VM from API.
        4. Do the basic sriov testing.
        """,
        priority=2,
        requirement=simple_requirement(
            min_nic_count=8,
            network_interface=features.Sriov(),
        ),
    )
    def verify_sriov_provision_with_max_nics_stop_start_from_platform(
        self, environment: Environment
    ) -> None:
        vm_nics = initialize_nic_info(environment)
        sriov_basic_test(environment, vm_nics)
        for node in environment.nodes.list():
            start_stop = node.features[StartStop]
            start_stop.stop()
            start_stop.start()
        sriov_basic_test(environment, vm_nics)

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
            network_interface=features.Sriov(),
        ),
    )
    def verify_sriov_reload_modules(self, environment: Environment) -> None:
        for node in environment.nodes.list():
            if node.tools[KernelConfig].is_built_in(get_used_config(node)):
                raise SkippedException(
                    "current VM's mlx driver is built-in, can not reload."
                )
        vm_nics = initialize_nic_info(environment)
        sriov_basic_test(environment, vm_nics)
        module_in_used: Dict[str, str] = {}
        for node in environment.nodes.list():
            module_in_used[node.name] = remove_module(node)
        sriov_vf_connection_test(environment, vm_nics, remove_module=True)
        for node in environment.nodes.list():
            load_module(node, module_in_used[node.name])
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
                nic_count=search_space.IntRange(min=3, max=8),
                data_path=schema.NetworkDataPath.Sriov,
            ),
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
                client_nic_info.upper, True
            )
            if device_sg_settings.sg_fixed:
                raise SkippedException(
                    "scatter-gather is fixed, it cannot be changed for device"
                    f" {client_nic_info.upper}. Skipping test."
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
        for node in environment.nodes.list():
            lspci = node.tools[Lspci]
            lspci.disable_devices_by_type(constants.DEVICE_TYPE_SRIOV)
            lspci.enable_devices()
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
        for client_nic_info in vm_nics[client_node.name].values():
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
            lspci.disable_devices_by_type(constants.DEVICE_TYPE_SRIOV)
            lspci.enable_devices()

        # check VF still paired with synthetic nic
        vm_nics = initialize_nic_info(environment)

        # check VF's scatter-gather feature keep consistent with previous status
        for client_nic_info in vm_nics[client_node.name].values():
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
            network_interface_feature.switch_sriov(enable=(not sriov_is_enabled))
        network_interface_feature.switch_sriov(enable=True)

        # check VF still paired with synthetic nic
        vm_nics = initialize_nic_info(environment)

        # check VF's scatter-gather feature keep consistent with previous status
        for client_nic_info in vm_nics[client_node.name].values():
            device_vf_sg_settings = client_ethtool.get_device_sg_settings(
                client_nic_info.lower, True
            )
            assert_that(
                device_vf_sg_settings.sg_setting,
                "sg setting is not sync into VF.",
            ).is_equal_to(False)

        # reload sriov modules
        module_built_in = any(
            node.tools[KernelConfig].is_built_in(get_used_config(node))
            for node in environment.nodes.list()
        )
        if not module_built_in:
            for node in environment.nodes.list():
                load_module(node, remove_module(node))

            # check VF still paired with synthetic nic
            vm_nics = initialize_nic_info(environment)

            # check VF's scatter-gather feature keep consistent with previous status
            for client_nic_info in vm_nics[client_node.name].values():
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
        iperf_log = dest_cat.read(client_iperf3_log, sudo=True, force_run=True)
        assert_that(iperf_log).does_not_contain("error")

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
        client_cpu_count = client_lscpu.get_core_count()

        vm_nics = initialize_nic_info(environment)

        server_iperf3 = server_node.tools[Iperf3]
        client_iperf3 = client_node.tools[Iperf3]
        # 1. Start iperf3 on server node.
        server_iperf3.run_as_server_async()
        client_interrupt_inspector = client_node.tools[InterruptInspector]
        for _, client_nic_info in vm_nics[client_node.name].items():
            # 2. Get initial interrupts sum per irq and cpu number on client node.
            # only collect 'Completion Queue Interrupts' irqs
            initial_pci_interrupts_by_irqs = (
                client_interrupt_inspector.sum_cpu_counter_by_irqs(
                    client_nic_info.pci_slot,
                    exclude_key_words=["pages", "cmd", "async"],
                )
            )

            initial_pci_interrupts_by_cpus = (
                client_interrupt_inspector.sum_cpu_counter_by_index(
                    client_nic_info.pci_slot
                )
            )
            assert_that(len(initial_pci_interrupts_by_cpus)).described_as(
                "initial cpu count of interrupts should be equal to cpu count"
            ).is_equal_to(client_cpu_count)
            matched_server_nic_info: NicInfo
            for _, server_nic_info in vm_nics[server_node.name].items():
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
                    exclude_key_words=["pages", "cmd", "async"],
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
                # 5. Compare interrupts changes, expected to see interrupts increased.
                assert_that(final_interrupts_value).described_as(
                    f"irq {init_irq_number} didn't have an increased interrupts count"
                    " after iperf3 run!"
                ).is_greater_than(init_interrupts_value)
            # 6. Get final interrupts sum per cpu on client node.
            final_pci_interrupts_by_cpus = (
                client_interrupt_inspector.sum_cpu_counter_by_index(
                    client_nic_info.pci_slot
                )
            )
            assert_that(len(final_pci_interrupts_by_cpus)).described_as(
                "final cpu count of interrupts should be equal to cpu count"
            ).is_equal_to(client_cpu_count)
            unused_cpu = 0
            for cpu, init_interrupts_value in initial_pci_interrupts_by_cpus.items():
                final_interrupts_value = final_pci_interrupts_by_cpus[cpu]
                # 7. Collect cpus which don't have interrupts count increased.
                if final_interrupts_value == init_interrupts_value:
                    unused_cpu += 1
            # 8. Compare interrupts count changes, expected half of cpus' interrupts
            #    increased.
            assert_that(client_cpu_count / 2).described_as(
                f"More than half of the vCPUs {unused_cpu} didn't have increased "
                "interrupt count!"
            ).is_greater_than(unused_cpu)

    def after_case(self, log: Logger, **kwargs: Any) -> None:
        environment: Environment = kwargs.pop("environment")
        cleanup_iperf3(environment)
