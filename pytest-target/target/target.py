"""Provides the abstract base `Target` class."""
from __future__ import annotations

import platform
import typing
from abc import ABC, abstractmethod
from io import BytesIO

import fabric  # type: ignore
import invoke  # type: ignore
from invoke.runners import Result  # type: ignore
from schema import Schema  # type: ignore
from tenacity import retry, stop_after_attempt, wait_exponential  # type: ignore

import lisa

if typing.TYPE_CHECKING:
    from typing import Any, Mapping, Set


class Target(ABC):
    """Extends 'fabric.Connection' with our own utilities."""

    # Typed instance attributes, not class attributes.
    parameters: Mapping[str, str]
    features: Set[str]
    name: str
    host: str
    conn: fabric.Connection

    def __init__(
        self,
        name: str,
        parameters: Mapping[str, str],
        features: Set[str],
    ):
        """Requires a unique name.

        Name is a unique identifier for the group of associated
        resources. Features is a list of requirements such as sriov,
        rdma, gpu, xdp. Parameters are used by `deploy()`.

        """
        self.name = name
        # TODO: Do we need to re-validate the parameters here?
        self.parameters = parameters
        self.features = features

        # TODO: Review this thoroughly as currently it depends on
        # parameters which is side-effecty.
        self.host = self.deploy()

        config = lisa.config.copy()
        config["run"]["env"] = {  # type: ignore
            # Set PATH since it’s not a login shell.
            "PATH": "/sbin:/usr/sbin:/usr/local/sbin:/bin:/usr/bin:/usr/local/bin"
        }
        self.connection = fabric.Connection(
            self.host, config=fabric.Config(overrides=config), inline_ssh_env=True
        )

    # TODO: Use an abstract class property to ensure this is defined.
    schema: Schema = Schema(None)

    # @property
    # @classmethod
    # @abstractmethod
    # def schema(cls) -> Schema:
    #     """Must return the parameters schema for setup."""
    #     ...

    @abstractmethod
    def deploy(self) -> str:
        """Must deploy the target resources and return hostname."""
        ...

    @abstractmethod
    def delete(self) -> None:
        """Must delete the target resources."""
        ...

    # A class attribute because it’s defined.
    local_context = invoke.Context(config=invoke.Config(overrides=lisa.config))

    @classmethod
    def local(cls, *args: Any, **kwargs: Any) -> Result:
        """This patches Fabric's 'local()' function to ignore SSH environment."""
        return Target.local_context.run(*args, **kwargs)

    # TODO: Refactor this. We don’t want to inherit from `Connection`
    # because that’s overly complicated. Honestly we probably just
    # want users to call `target.conn.run()` etc.
    def run(self, *args: Any, **kwargs: Any) -> Result:
        return self.connection.run(*args, **kwargs)

    def sudo(self, *args: Any, **kwargs: Any) -> Result:
        return self.connection.sudo(*args, **kwargs)

    def get(self, *args: Any, **kwargs: Any) -> Result:
        return self.connection.get(*args, **kwargs)

    def put(self, *args: Any, **kwargs: Any) -> Result:
        return self.connection.put(*args, **kwargs)

    @retry(reraise=True, wait=wait_exponential(), stop=stop_after_attempt(3))
    def ping(self, **kwargs: Any) -> Result:
        """Ping the node from the local system in a cross-platform manner."""
        flag = "-c 1" if platform.system() == "Linux" else "-n 1"
        return self.local(f"ping {flag} {self.host}", **kwargs)

    def cat(self, path: str) -> str:
        """Gets the value of a remote file without a temporary file."""
        with BytesIO() as buf:
            self.get(path, buf)
            return buf.getvalue().decode("utf-8").strip()


class Local(Target):
    schema: Schema = Schema(None)

    def deploy(self) -> str:
        return "localhost"

    def delete(self) -> None:
        pass
