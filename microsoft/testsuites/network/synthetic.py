# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from typing import Dict

from assertpy import assert_that

from lisa import (
    Environment,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    schema,
    simple_requirement,
)
from lisa.features import NetworkInterface
from lisa.nic import NicInfo, Nics


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
    def synthetic_provision_with_max_nics_validation(
        self, environment: Environment
    ) -> None:
        self._initialize_nic_info(environment)

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
        requirement=simple_requirement(
            network_interface=schema.NetworkInterfaceOptionSettings(
                data_path=schema.NetworkDataPath.Synthetic,
                max_nic_count=8,
            ),
        ),
    )
    def synthetic_add_max_nics_one_time_after_provision_validation(
        self, environment: Environment
    ) -> None:
        for node in environment.nodes.list():
            network_interface_feature = node.features[NetworkInterface]
            network_interface_feature.attach_nics(
                extra_nic_count=7, enable_accelerated_networking=False
            )
        self._initialize_nic_info(environment)

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
        requirement=simple_requirement(
            network_interface=schema.NetworkInterfaceOptionSettings(
                data_path=schema.NetworkDataPath.Synthetic,
                max_nic_count=8,
            ),
        ),
    )
    def synthetic_add_max_nics_one_by_one_after_provision_validation(
        self, environment: Environment
    ) -> None:
        for node in environment.nodes.list():
            network_interface_feature = node.features[NetworkInterface]
            for _ in range(7):
                network_interface_feature.attach_nics(
                    extra_nic_count=1, enable_accelerated_networking=False
                )
                self._initialize_nic_info(environment)

    def _initialize_nic_info(
        self, environment: Environment
    ) -> Dict[str, Dict[str, NicInfo]]:
        vm_nics: Dict[str, Dict[str, NicInfo]] = {}
        for node in environment.nodes.list():
            node_nic_info = Nics(node)
            node_nic_info.initialize()
            vm_nics[node.name] = node_nic_info.nics
            for _, node_nic in node_nic_info.nics.items():
                assert_that(node_nic.ip_addr).described_as(
                    f"This interface {node_nic.upper} does not have a IP address."
                ).is_not_empty()
        return vm_nics
