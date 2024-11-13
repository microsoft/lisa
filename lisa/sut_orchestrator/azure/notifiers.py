# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Set, Type

from dataclasses_json import dataclass_json

from lisa import messages, notifier, schema
from lisa.environment import EnvironmentMessage, EnvironmentStatus
from lisa.util import LisaException, constants
from lisa.util.logger import Logger

from .. import AZURE
from .common import AzureLocation, AzureNodeSchema, load_location_info_from_file


@dataclass
class VmsizeBasicInfo:
    name: str = ""
    vm_family: str = ""
    core_count: int = 0


@dataclass
class EnvironmentVmsizeInfo:
    name: str
    status: EnvironmentStatus = EnvironmentStatus.New
    vm_sizes: List[VmsizeBasicInfo] = field(default_factory=list)


@dataclass_json()
@dataclass
class AzureNotifierSchema(schema.Notifier):
    # fields to query test failure and test cases
    file_name: str = "azure_usage_counter.json"


class AzureNotifier(notifier.Notifier):
    """
    This notifier is used to collect the core usage information, which can then guide
    the quota request in the subscription.
    """

    def __init__(self, runbook: AzureNotifierSchema) -> None:
        notifier.Notifier.__init__(self, runbook)
        self._file_name = runbook.file_name

    @classmethod
    def type_name(cls) -> str:
        return "azure_usage_counter"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return AzureNotifierSchema

    def _received_message(self, message: messages.MessageBase) -> None:
        if isinstance(message, EnvironmentMessage):
            self._process_environment_message(message)
        else:
            raise LisaException(f"unsupported message received, {type(message)}")

    def _subscribed_message_type(self) -> List[Type[messages.MessageBase]]:
        return [EnvironmentMessage]

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        env_path = constants.RUN_LOCAL_LOG_PATH / "environments"
        env_path.mkdir(exist_ok=True, parents=True)
        self._file_path = env_path / self._file_name
        self._counter_log_path = env_path / "azure_usage_counter_collection.log"
        self._locations_data_cache: Dict[str, Any] = {}
        self._created_envs: Set[str] = set()
        self._max_cores: Dict[str, int] = {}
        self._current_cores: Dict[str, int] = {}
        self._write_header = True

    def _process_environment_message(self, msg: EnvironmentMessage) -> None:
        if (
            msg.status != EnvironmentStatus.Deployed
            and msg.status != EnvironmentStatus.Deleted
        ):
            return

        if (
            msg.status == EnvironmentStatus.Deleted
            and msg.name not in self._created_envs
        ):
            # Some skipped runs caused by no available environment has deleted message
            # without deployed message. Ignore it.
            return

        env = EnvironmentVmsizeInfo(name=msg.name, status=msg.status)
        assert msg.runbook.nodes_requirement
        for node in msg.runbook.nodes_requirement:
            node_runbook = node.get_extended_runbook(AzureNodeSchema, AZURE)
            location = node_runbook.location
            vm_size = node_runbook.vm_size
            location_data = self._get_location_info(location, self._log)
            assert isinstance(location_data, AzureLocation)
            vm_size_info = location_data.capabilities.get(vm_size, None)
            if vm_size_info:
                vm_family = vm_size_info.resource_sku["family"]
                core_count = vm_size_info.capability.core_count
                assert isinstance(core_count, int), f"actual: {type(core_count)}"
            else:
                vm_family = "unknown"
                core_count = 0
            env.vm_sizes.append(
                VmsizeBasicInfo(
                    name=vm_size, vm_family=vm_family, core_count=core_count
                )
            )
        if msg.name not in self._created_envs:
            self._created_envs.add(msg.name)

        if msg.status == EnvironmentStatus.Deleted:
            self._created_envs.remove(msg.name)

        self._update_information(env)
        self._dump_core_stats()

    def _get_location_info(self, location: str, log: Logger) -> Any:
        location_data = self._locations_data_cache.get(location, None)
        if not location_data:
            cached_file_name = constants.CACHE_PATH.joinpath(
                f"azure_locations_{location}.json"
            )
            location_data = load_location_info_from_file(
                cached_file_name=cached_file_name, log=log
            )

        assert location_data
        self._locations_data_cache[location] = location_data
        return location_data

    def _update_information(self, env: EnvironmentVmsizeInfo) -> None:
        if self._write_header:
            with open(self._counter_log_path, "w") as f:
                f.write(
                    f"{'name':<15} {'node':<15} {'status':<15} {'vm_size':<30} "
                    f"{'vm_family':<30} {'cores':<15} {'current cores':<15} "
                    f"{'max cores':<15}\n"
                )
            self._write_header = False

        node_index = 0
        with open(self._counter_log_path, "a") as f:
            for vm_size in env.vm_sizes:
                self._update_cores_info(
                    vm_size.vm_family, vm_size.core_count, env.status
                )
                f.write(
                    f"{env.name:<15} {node_index:<15} {env.status.name:<15}"
                    f"{vm_size.name:<30} {vm_size.vm_family:<30} "
                    f"{vm_size.core_count:<15} "
                    f"{self._current_cores[vm_size.vm_family]:<15} "
                    f"{self._max_cores[vm_size.vm_family]:<15}\n"
                )
                node_index += 1

    def _update_cores_info(
        self, vm_family: str, core_count: int, status: EnvironmentStatus
    ) -> None:
        if status == EnvironmentStatus.Deployed:
            current_core_count = core_count + self._current_cores.get(vm_family, 0)
            self._current_cores[vm_family] = current_core_count
            self._max_cores[vm_family] = max(
                self._max_cores.get(vm_family, 0), self._current_cores[vm_family]
            )
        elif status == EnvironmentStatus.Deleted:
            self._current_cores[vm_family] -= core_count

    def _dump_core_stats(self) -> None:
        azure_usage_counter = json.dumps(self._max_cores, indent=4)
        with open(self._file_path, "w") as f:
            f.write(azure_usage_counter)
