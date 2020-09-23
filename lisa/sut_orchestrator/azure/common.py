from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from azure.mgmt.compute import ComputeManagementClient  # type: ignore

from lisa.environment import Environment
from lisa.node import Node

if TYPE_CHECKING:
    from .platform_ import AzurePlatform

AZURE = "azure"


@dataclass
class EnvironmentContext:
    resource_group_name: str = ""
    resource_group_is_created: bool = False


@dataclass
class NodeContext:
    resource_group_name: str = ""
    vm_name: str = ""
    username: str = ""
    password: str = ""
    private_key_file: str = ""


def get_compute_client(platform: Any) -> ComputeManagementClient:
    # there is cycle import, if assert type.
    # so it just use typing here only, no assertion.
    azure_platform: AzurePlatform = platform
    return ComputeManagementClient(
        credential=azure_platform.credential,
        subscription_id=azure_platform.subscription_id,
    )


def get_node_context(node: Node) -> NodeContext:
    return node.get_context(NodeContext)


def get_environment_context(environment: Environment) -> EnvironmentContext:
    return environment.get_context(EnvironmentContext)


def wait_operation(operation: Any) -> Any:
    # to support timeout in future
    return operation.wait()
