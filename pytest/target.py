from __future__ import annotations

import platform
import typing
from abc import ABC, abstractmethod
from io import BytesIO
from uuid import uuid4

from fabric import Config as FabricConfig
from fabric import Connection
from invoke import Config as InvokeConfig
from invoke import Context
from invoke.runners import Result  # type: ignore
from tenacity import retry, stop_after_attempt, wait_exponential  # type: ignore

import lisa

if typing.TYPE_CHECKING:
    from typing import Any, Dict, Set


class Target(ABC):
    """Extends 'fabric.Connection' with our own utilities."""

    local_context = Context(config=InvokeConfig(overrides=lisa.config))

    def __init__(
        self,
        params: Dict[str, str],
        features: Set[str],
        name: str = f"pytest-{uuid4()}",
    ):
        """If not given a name, generates one uniquely.

        Name is a unique identifier for the group of associated
        resources. Features is a list of requirements such as sriov,
        rdma, gpu, xdp.

        """
        self.params: Dict[str, str] = params
        self.features: Set[str] = features
        self.name: str = name

        # TODO: Fix this.
        self.host = self.deploy()

        config = lisa.config.copy()
        config["run"]["env"] = {
            # Set PATH since it’s not a login shell.
            "PATH": "/sbin:/usr/sbin:/usr/local/sbin:/bin:/usr/bin:/usr/local/bin"
        }
        self.connection = Connection(
            self.host, config=FabricConfig(overrides=config), inline_ssh_env=True
        )

    @abstractmethod
    def deploy(self) -> str:
        """Must deploy the target resources and return hostname."""
        ...

    @abstractmethod
    def delete(self) -> None:
        """Must delete the target resources."""
        ...

    @classmethod
    def local(self, *args: Any, **kwargs: Any) -> Result:
        """This patches Fabric's 'local()' function to ignore SSH environment."""
        return Target.local_context.run(*args, **kwargs)

    # TODO: Generate these automatically. There’s some weird bug with
    # inheriting from ‘Connection’ that causes infinite recursion.
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
