# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.case import TestCase

from azure.mgmt.compute.models import ResourceSku  # type: ignore

from lisa import schema, search_space
from lisa.environment import Environment
from lisa.sut_orchestrator.azure import common, platform_
from lisa.util import LisaException, constants
from lisa.util.logger import get_logger


class AzurePrepareTestCase(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        constants.CACHE_PATH = Path(__file__).parent

    def setUp(self) -> None:
        self._log = get_logger("test", "azure")

        platform_runbook = schema.Platform()
        self._platform = platform_.AzurePlatform(platform_runbook)
        self._platform._azure_runbook = platform_.AzurePlatformSchema()

        # trigger data to be cached
        locations = ["westus2", "eastus2", "notreal"]
        for location in locations:
            self._platform._get_eligible_vm_sizes(location, self._log)

    def test_load_capability(self) -> None:
        # capability can be loaded correct
        # expected test data is from json file
        assert self._platform._locations_data_cache
        resource_sku: Dict[str, Any] = ResourceSku.from_dict(
            {
                "resource_type": "virtualMachines",
                "name": "Standard_NV48s_v3",
                "tier": "Standard",
                "size": "NV48s_v3",
                "family": "standardNVSv3Family",
                "locations": ["eastus2"],
                "location_info": [
                    {"location": "eastus2", "zones": ["3"], "zone_details": []}
                ],
                "capabilities": [
                    {"name": "MaxResourceVolumeMB", "value": "1376256"},
                    {"name": "OSVhdSizeMB", "value": "1047552"},
                    {"name": "vCPUs", "value": "48"},
                    {"name": "MemoryGB", "value": "448"},
                    {"name": "vCPUsAvailable", "value": "48"},
                    {"name": "GPUs", "value": "4"},
                    {"name": "vCPUsPerCore", "value": "2"},
                    {"name": "MaxDataDiskCount", "value": "32"},
                    {"name": "EncryptionAtHostSupported", "value": "True"},
                    {"name": "AcceleratedNetworkingEnabled", "value": "False"},
                    {"name": "MaxNetworkInterfaces", "value": "8"},
                ],
                "restrictions": [],
            }
        )
        node = self._platform._resource_sku_to_capability("eastus2", resource_sku)
        self.assertEqual(48, node.core_count)
        self.assertEqual(458752, node.memory_mb)
        assert node.network_interface
        self.assertEqual(
            search_space.IntRange(min=1, max=8), node.network_interface.nic_count
        )
        assert node.disk
        self.assertEqual(
            search_space.IntRange(min=0, max=32), node.disk.data_disk_count
        )
        self.assertEqual(4, node.gpu_count)

    def test_not_eligible_dropped(self) -> None:
        # if a vm size doesn't exists, it should be dropped.
        # if a location is not eligible, it should be dropped.
        self.verify_exists_vm_size("westus2", "Standard_D8a_v3", True)
        assert self._platform._locations_data_cache
        self.assertTrue("notreal" in self._platform._locations_data_cache)

        assert self._platform._eligible_capabilities
        self.verify_eligible_vm_size("westus2", "notreal", False)
        self.assertTrue("notreal" in self._platform._eligible_capabilities)
        self.assertFalse(self._platform._eligible_capabilities["notreal"])

    def test_predefined_2nd_location(self) -> None:
        # location predefined in eastus2, so all prepared skip westus2
        env = self.load_environment(node_req_count=2)
        self.verify_prepared_nodes(
            expected_result=True,
            expected_locations=["westus2", "westus2"],
            expected_vm_sizes=["Standard_DS2_v2", "Standard_DS2_v2"],
            expected_cost=4,
            environment=env,
        )

        env = self.load_environment(node_req_count=2)
        self.set_node_runbook(env, 1, location="eastus2")
        self.verify_prepared_nodes(
            expected_result=True,
            expected_locations=["eastus2", "eastus2"],
            expected_vm_sizes=["Standard_DS2_v2", "Standard_DS2_v2"],
            expected_cost=4,
            environment=env,
        )

    def test_predefined_only_size(self) -> None:
        # predefined an eastus2 vm size, so all are to eastus2
        env = self.load_environment(node_req_count=2)
        self.set_node_runbook(env, 1, location="", vm_size="Standard_B1ls")
        self.verify_prepared_nodes(
            expected_result=True,
            expected_locations=["eastus2", "eastus2"],
            expected_vm_sizes=["Standard_DS2_v2", "Standard_B1ls"],
            expected_cost=3,
            environment=env,
        )

    def test_predefined_with_3_nic(self) -> None:
        # 3 nic cannot be met by Standard_DS2_v2, as it support at most 2 nics
        # the code path of predefined and normal is different, so test it twice
        env = self.load_environment(node_req_count=1)
        assert env.runbook.nodes_requirement
        env.runbook.nodes_requirement.append(
            schema.NodeSpace(
                network_interface=schema.NetworkInterfaceOptionSettings(nic_count=3)
            )
        )
        self.set_node_runbook(env, 1, location="eastus2")
        self.verify_prepared_nodes(
            expected_result=True,
            expected_locations=["eastus2", "eastus2"],
            expected_vm_sizes=["Standard_DS2_v2", "Standard_DS15_v2"],
            expected_cost=22,
            environment=env,
        )

    def test_predefined_inconsistent_location_failed(self) -> None:
        # two locations westus2, and eastus2 predefined, so failed.
        env = self.load_environment(node_req_count=2)
        self.set_node_runbook(env, 0, location="eastus2")
        self.set_node_runbook(env, 1, location="westus2")
        with self.assertRaises(LisaException) as cm:
            self._platform._prepare_environment(env, self._log)
        message = (
            "predefined node must be in same location, "
            "previous: eastus2, found: westus2"
        )
        self.assertEqual(message, str(cm.exception)[0 : len(message)])

    def test_no_predefined_location_use_default_locations(self) -> None:
        # no predefined location found, use default location list
        env = self.load_environment(node_req_count=1)
        self.verify_prepared_nodes(
            expected_result=True,
            expected_locations=["westus2"],
            expected_vm_sizes=["Standard_DS2_v2"],
            expected_cost=2,
            environment=env,
        )

    def test_use_predefined_vm_size(self) -> None:
        # there is predefined vm size, and out of default scope, but use it
        env = self.load_environment(node_req_count=1)
        self.set_node_runbook(env, 0, location="", vm_size="Standard_NV48s_v3")
        # 448: 48 cores + 100 * 4 gpus
        self.verify_prepared_nodes(
            expected_result=True,
            expected_locations=["eastus2"],
            expected_vm_sizes=["Standard_NV48s_v3"],
            expected_cost=448,
            environment=env,
        )

    def test_predefined_not_found_vm_size(self) -> None:
        # vm size is not found
        env = self.load_environment(node_req_count=1)
        self.set_node_runbook(env, 0, location="", vm_size="not_exist")
        # The mock up capability is matched.
        self.verify_prepared_nodes(
            expected_result=True,
            expected_locations=["westus2"],
            expected_vm_sizes=["not_exist"],
            expected_cost=0,
            environment=env,
        )

    def test_predefined_wont_be_override(self) -> None:
        # predefined node won't be overridden in loop
        env = self.load_environment(node_req_count=3)
        self.set_node_runbook(env, 1, location="", vm_size="Standard_A8_v2")
        self.set_node_runbook(env, 2, location="eastus2", vm_size="")
        self.verify_prepared_nodes(
            expected_result=True,
            expected_locations=["eastus2", "eastus2", "eastus2"],
            expected_vm_sizes=["Standard_DS2_v2", "Standard_A8_v2", "Standard_DS2_v2"],
            expected_cost=12,
            environment=env,
        )

    def test_partial_match(self) -> None:
        # the "A2" should match Standard_A2_v2, instead of Standard_A2m_v2. The
        # test data has two Standard_A2m_v2, so the test case can gurantee the
        # problem won't be hidden by different behavior.
        env = self.load_environment(node_req_count=2)
        self.set_node_runbook(env, 0, location="", vm_size="A2m")
        self.set_node_runbook(env, 1, location="", vm_size="A2")
        self.verify_prepared_nodes(
            expected_result=True,
            expected_locations=["westus2", "westus2"],
            expected_vm_sizes=["Standard_A2m_v2", "Standard_A2_v2"],
            expected_cost=4,
            environment=env,
        )

    def test_normal_req_in_same_location(self) -> None:
        # normal requirement will be in same location of predefined
        env = self.load_environment(node_req_count=2)
        self.set_node_runbook(env, 1, location="eastus2", vm_size="")
        self.verify_prepared_nodes(
            expected_result=True,
            expected_locations=["eastus2", "eastus2"],
            expected_vm_sizes=["Standard_DS2_v2", "Standard_DS2_v2"],
            expected_cost=4,
            environment=env,
        )

    def test_count_normal_cost(self) -> None:
        # predefined vm size also count the cost
        env = self.load_environment(node_req_count=2)
        self.verify_prepared_nodes(
            expected_result=True,
            expected_locations=["westus2", "westus2"],
            expected_vm_sizes=["Standard_DS2_v2", "Standard_DS2_v2"],
            expected_cost=4,
            environment=env,
        )

    def test_normal_may_fit_2nd_location(self) -> None:
        # normal req may fit into 2nd location, as 1st location not meet requirement
        env = self.load_environment(node_req_count=1)
        assert env.runbook.nodes_requirement
        env.runbook.nodes_requirement.append(
            schema.NodeSpace(memory_mb=search_space.IntRange(min=143360))
        )
        self.verify_prepared_nodes(
            expected_result=True,
            expected_locations=["eastus2", "eastus2"],
            expected_vm_sizes=["Standard_DS2_v2", "Standard_DS15_v2"],
            expected_cost=22,
            environment=env,
        )

    def test_normal_may_fit_2nd_batch_vm(self) -> None:
        # fit 2nd batch of candidates
        env = self.load_environment(node_req_count=1)
        assert env.runbook.nodes_requirement
        env.runbook.nodes_requirement.append(
            schema.NodeSpace(core_count=8, memory_mb=16384)
        )
        self.verify_prepared_nodes(
            expected_result=True,
            expected_locations=["eastus2", "eastus2"],
            expected_vm_sizes=["Standard_DS2_v2", "Standard_A8_v2"],
            expected_cost=10,
            environment=env,
        )

    def test_normal_with_3_nic(self) -> None:
        # 3 nic cannot be met by Standard_DS2_v2, as it support at most 2 nics
        # the code path of predefined and normal is different, so test it twice
        env = self.load_environment(node_req_count=1)
        assert env.runbook.nodes_requirement
        env.runbook.nodes_requirement.append(
            schema.NodeSpace(
                network_interface=schema.NetworkInterfaceOptionSettings(nic_count=3)
            )
        )
        self.verify_prepared_nodes(
            expected_result=True,
            expected_locations=["eastus2", "eastus2"],
            expected_vm_sizes=["Standard_DS2_v2", "Standard_DS15_v2"],
            expected_cost=22,
            environment=env,
        )

    def verify_exists_vm_size(
        self, location: str, vm_size: str, expect_exists: bool
    ) -> Optional[platform_.AzureCapability]:
        result = None
        location_info = self._platform._get_location_info(location, self._log)
        self.assertEqual(
            expect_exists,
            any([x.vm_size == vm_size for x in location_info.capabilities]),
        )
        if expect_exists:
            result = next(x for x in location_info.capabilities if x.vm_size == vm_size)
        return result

    def verify_eligible_vm_size(
        self, location: str, vm_size: str, expect_exists: bool
    ) -> Optional[platform_.AzureCapability]:
        result = None
        assert self._platform._eligible_capabilities
        self.assertEqual(
            expect_exists,
            any(
                [
                    x.vm_size == vm_size
                    for x in self._platform._eligible_capabilities[location]
                ]
            ),
        )
        if expect_exists:
            result = next(
                x
                for x in self._platform._eligible_capabilities[location]
                if x.vm_size == vm_size
            )
        return result

    def load_environment(
        self,
        node_req_count: int = 2,
    ) -> Environment:
        runbook = schema.Environment()
        if node_req_count > 0:
            runbook.nodes_requirement = []
            for _ in range(node_req_count):
                node_req = schema.NodeSpace()
                _ = node_req.get_extended_runbook(common.AzureNodeSchema, common.AZURE)
                runbook.nodes_requirement.append(node_req)
        environment = Environment(
            is_predefined=True, warn_as_error=False, id_=0, runbook=runbook
        )

        return environment

    def set_node_runbook(
        self,
        environment: Environment,
        index: int,
        location: str = "",
        vm_size: str = "",
    ) -> None:
        assert environment.runbook.nodes_requirement
        node_runbook = environment.runbook.nodes_requirement[
            index
        ].get_extended_runbook(common.AzureNodeSchema, common.AZURE)
        node_runbook.location = location
        node_runbook.vm_size = vm_size

    def verify_prepared_nodes(
        self,
        expected_result: bool,
        expected_locations: List[str],
        expected_vm_sizes: List[str],
        expected_cost: int,
        environment: Environment,
    ) -> None:
        actual_result = self._platform._prepare_environment(environment, self._log)
        self.assertEqual(expected_result, actual_result)

        if expected_locations:
            assert environment.runbook.nodes_requirement

            # get node runbook for validating
            nodes_runbook = [
                x.get_extended_runbook(common.AzureNodeSchema, common.AZURE)
                for x in environment.runbook.nodes_requirement
            ]

            self.assertListEqual(
                expected_locations,
                [x.location for x in nodes_runbook],
            )
            self.assertListEqual(
                expected_vm_sizes,
                [x.vm_size for x in nodes_runbook],
            )

            # all cap values must be covered to specified int value, not space
            for node_cap in environment.runbook.nodes_requirement:
                assert node_cap
                assert node_cap.disk
                assert node_cap.network_interface
                self.assertIsInstance(node_cap.core_count, int)
                self.assertIsInstance(node_cap.memory_mb, int)
                self.assertIsInstance(node_cap.disk.data_disk_count, int)
                self.assertIsInstance(node_cap.network_interface.nic_count, int)
                self.assertIsInstance(node_cap.gpu_count, int)

                self.assertLessEqual(1, node_cap.core_count)
                self.assertLessEqual(512, node_cap.memory_mb)
                self.assertLessEqual(0, node_cap.disk.data_disk_count)
                self.assertLessEqual(1, node_cap.network_interface.nic_count)
                self.assertLessEqual(0, node_cap.gpu_count)

        self.assertEqual(expected_cost, environment.cost)
