# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from lisa import (
    Environment,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    schema,
    simple_requirement,
)
from lisa.features import NetworkInterface, StartStop

from .common import initialize_nic_info, remove_extra_nics, restore_extra_nics


@TestSuiteMetadata(
    area="network",
    category="functional",
    description="""
    This test suite uses to verify synthetic network functionality.
    """,
)
class Synthetic(TestSuite):
    TIME_OUT = 300

    @TestCaseMetadata(
        description="""
        This case verify VM works well when provison with max (8) synthetic nics.

        Steps,
        1. Provision VM with max network interfaces with synthetic network.
        2. Check each nic has an ip address.
        """,
        priority=2,
        requirement=simple_requirement(
            min_nic_count=8,
            network_interface=schema.NetworkInterfaceOptionSettings(
                data_path=schema.NetworkDataPath.Synthetic,
            ),
        ),
    )
    def verify_synthetic_provision_with_max_nics(
        self, environment: Environment
    ) -> None:
        initialize_nic_info(environment, is_sriov=False)

    @TestCaseMetadata(
        description="""
        This case verify VM works well when provison with max (8) synthetic nics.

        Steps,
        1. Provision VM with max network interfaces with synthetic network.
        2. Check each nic has an ip address.
        3. Reboot VM from guest.
        4. Check each nic has an ip address.
        """,
        priority=2,
        requirement=simple_requirement(
            min_nic_count=8,
            network_interface=schema.NetworkInterfaceOptionSettings(
                data_path=schema.NetworkDataPath.Synthetic,
            ),
        ),
    )
    def verify_synthetic_provision_with_max_nics_reboot(
        self, environment: Environment
    ) -> None:
        initialize_nic_info(environment, is_sriov=False)
        for node in environment.nodes.list():
            node.reboot()
        initialize_nic_info(environment, is_sriov=False)

    @TestCaseMetadata(
        description="""
        This case verify VM works well when provison with max (8) synthetic nics.

        Steps,
        1. Provision VM with max network interfaces with synthetic network.
        2. Check each nic has an ip address.
        3. Reboot VM from API.
        4. Check each nic has an ip address.
        """,
        priority=2,
        requirement=simple_requirement(
            min_nic_count=8,
            network_interface=schema.NetworkInterfaceOptionSettings(
                data_path=schema.NetworkDataPath.Synthetic,
            ),
        ),
    )
    def verify_synthetic_provision_with_max_nics_reboot_from_platform(
        self, environment: Environment
    ) -> None:
        initialize_nic_info(environment, is_sriov=False)
        for node in environment.nodes.list():
            start_stop = node.features[StartStop]
            start_stop.restart()
        initialize_nic_info(environment, is_sriov=False)

    @TestCaseMetadata(
        description="""
        This case verify VM works well when provison with max (8) synthetic nics.

        Steps,
        1. Provision VM with max network interfaces with synthetic network.
        2. Check each nic has an ip address.
        3. Stop and Start VM from API.
        4. Check each nic has an ip address.
        """,
        priority=2,
        requirement=simple_requirement(
            min_nic_count=8,
            network_interface=schema.NetworkInterfaceOptionSettings(
                data_path=schema.NetworkDataPath.Synthetic,
            ),
        ),
    )
    def verify_synthetic_provision_with_max_nics_stop_start_from_platform(
        self, environment: Environment
    ) -> None:
        initialize_nic_info(environment, is_sriov=False)
        for node in environment.nodes.list():
            start_stop = node.features[StartStop]
            start_stop.stop()
            start_stop.start()
        initialize_nic_info(environment, is_sriov=False)

    @TestCaseMetadata(
        description="""
        This case verify VM works well after attaching 7 extra synthetic nics
         in one time.

        Steps,
        1. Provision VM with 1 network interface with synthetic network.
        2. Add 7 extra network interfaces in one time.
        3. Check each nic has an ip address.
        """,
        priority=2,
        use_new_environment=True,
        requirement=simple_requirement(
            network_interface=schema.NetworkInterfaceOptionSettings(
                data_path=schema.NetworkDataPath.Synthetic,
                max_nic_count=8,
            ),
        ),
    )
    def verify_synthetic_add_max_nics_one_time_after_provision(
        self, environment: Environment
    ) -> None:
        remove_extra_nics(environment)
        try:
            for node in environment.nodes.list():
                network_interface_feature = node.features[NetworkInterface]
                network_interface_feature.attach_nics(
                    extra_nic_count=7, enable_accelerated_networking=False
                )
            initialize_nic_info(environment, is_sriov=False)
        finally:
            restore_extra_nics(environment)

    @TestCaseMetadata(
        description="""
        This case verify VM works well after attaching 7 extra synthetic nics
         one by one.

        Steps,
        1. Provision VM with 1 network interface with synthetic network.
        2. Add 7 extra network interfaces one by one.
        3. Check each nic has an ip address.
        """,
        priority=2,
        use_new_environment=True,
        requirement=simple_requirement(
            network_interface=schema.NetworkInterfaceOptionSettings(
                data_path=schema.NetworkDataPath.Synthetic,
                max_nic_count=8,
            ),
        ),
    )
    def verify_synthetic_add_max_nics_one_by_one_after_provision(
        self, environment: Environment
    ) -> None:
        remove_extra_nics(environment)
        try:
            for node in environment.nodes.list():
                network_interface_feature = node.features[NetworkInterface]
                for _ in range(7):
                    network_interface_feature.attach_nics(
                        extra_nic_count=1, enable_accelerated_networking=False
                    )
                    initialize_nic_info(environment, is_sriov=False)
        finally:
            restore_extra_nics(environment)
