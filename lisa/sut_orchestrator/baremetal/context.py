from dataclasses import dataclass

from lisa import schema
from lisa.environment import Environment
from lisa.node import Node

from .build import Build


@dataclass
class EnvironmentContext:
    ssh_public_key: str = ""


@dataclass
class NodeContext:
    connection: schema.ConnectionInfo = schema.ConnectionInfo(password="mock")


@dataclass
class BuildContext:
    is_copied: bool = False


def get_environment_context(environment: Environment) -> EnvironmentContext:
    return environment.get_context(EnvironmentContext)


def get_node_context(node: Node) -> NodeContext:
    return node.get_context(NodeContext)


def get_build_context(build: Build) -> BuildContext:
    return build.get_context(BuildContext)
