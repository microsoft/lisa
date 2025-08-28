# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
from pathlib import Path
from typing import Any, Dict, List, cast

from assertpy import assert_that

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
    Iperf3,
    Journalctl,
    Lscpu,
    Service,
)
from lisa.util import (
    LisaException,
    LisaTimeoutException,
    UnsupportedDistroException,
    check_till_timeout,
)
from lisa.util.shell import wait_tcp_port_ready
from microsoft.testsuites.network.common import (
    cleanup_iperf3,
    disable_enable_devices,
    initialize_nic_info,
    reload_modules,
    remove_extra_nics,
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
        sriov_basic_test(environment)
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
        vm_nics = initialize_nic_info(environment)
        sriov_basic_test(environment)
        sriov_vf_connection_test(environment, vm_nics, turn_off_lower=True)

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
        initialize_nic_info(environment)
        sriov_basic_test(environment)

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
        initialize_nic_info(environment)
        sriov_basic_test(environment)
        for node in environment.nodes.list():
            node.reboot()
        initialize_nic_info(environment)
        sriov_basic_test(environment)

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
        initialize_nic_info(environment)
        sriov_basic_test(environment)
        for node in environment.nodes.list():
            start_stop = node.features[StartStop]
            start_stop.restart()
        initialize_nic_info(environment)
        sriov_basic_test(environment)

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
            min_nic_count=8,
            network_interface=features.Sriov(),
        ),
    )
    def verify_sriov_reload_modules(self, environment: Environment) -> None:
        vm_nics = initialize_nic_info(environment)
        sriov_basic_test(environment)

        module_in_used: Dict[str, List[str]] = {}
        module_name_list: List[str] = []
        for node in environment.nodes.list():
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
                nic_count=search_space.IntRange(min=3, max=8),
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
        server_node = cast(RemoteNode, environment.nodes[0])
        client_node = cast(RemoteNode, environment.nodes[1])

        if (
            server_node.execute(
                "command -v irqbalance", shell=True, sudo=True
            ).exit_code
            != 0
        ):
            raise SkippedException("irqbalance is not installed")

        # Get the irqbalance version if we can
        if isinstance(server_node.os, Posix):
            try:
                log.debug(
                    "irqbalance version: "
                    f"{server_node.os.get_package_information('irqbalance')}"
                )
            except Exception:
                log.debug("irqbalance version: not found")

        server_node.tools[Service].stop_service("irqbalance")

        irqbalance = server_node.execute_async("irqbalance --debug", sudo=True)

        server_iperf3 = server_node.tools[Iperf3]
        client_iperf3 = client_node.tools[Iperf3]

        server_iperf3.run_as_server_async()
        client_iperf3.run_as_client(
            server_ip=server_node.internal_address,
            run_time_seconds=240,
            parallel_number=128,
            client_ip=client_node.internal_address,
        )

        irqbalance.kill()
        result = irqbalance.wait_result()
        assert re.search(
            "Selecting irq [0-9]+ for rebalancing",
            result.stdout,
        ), "irqbalance is not rebalancing irqs"

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
