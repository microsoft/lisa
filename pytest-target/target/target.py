"""Provides the abstract base `Target` class."""
from __future__ import annotations

import platform
import typing
from abc import ABC, abstractmethod
from io import BytesIO

import fabric  # type: ignore
import invoke  # type: ignore
import schema  # type: ignore
from invoke.runners import Result  # type: ignore
from tenacity import retry, stop_after_attempt, wait_exponential  # type: ignore

if typing.TYPE_CHECKING:
    from typing import Any, Mapping, Set


class Target(ABC):
    """This class represents a remote Linux target.

    As a partially abstract base class, it is meant to be subclassed
    to provide platform support. So `Target` as a class maps to the
    concept of a Linux target machine reachable via SSH (through
    `self.conn`, an instance of `Fabric.Connection`). Each subclass of
    `Target` provides the necessary implementation to instantiate an
    actual Linux target, by deploying it on that platform. Each
    _instance_ of a platform-specific subclass of `Target` maps to an
    actual Linux target that has been deployed on that platform.

    """

    # Typed instance attributes, not class attributes.
    params: Mapping[str, str]
    features: Set[str]
    name: str
    host: str
    conn: fabric.Connection

    # Setup a sane configuration for local and remote commands. Note
    # that the defaults between Fabric and Invoke are different, so we
    # use their Config classes explicitly later.
    config = {
        "run": {
            # Show each command as its run.
            "echo": True,
            # Disable stdin forwarding.
            "in_stream": False,
            # Don’t let remote commands take longer than five minutes
            # (unless later overridden). This is to prevent hangs.
            "command_timeout": 1200,
        }
    }

    def __init__(
        self,
        name: str,
        params: Mapping[str, str],
        features: Set[str],
    ):
        """Requires a unique name.

        Name is a unique identifier for the group of associated
        resources. Features is a list of requirements such as sriov,
        rdma, gpu, xdp. Parameters are used by `deploy()`.

        """
        self.name = name
        # TODO: Do we need to re-validate the parameters here?
        self.params = params
        self.features = features

        # TODO: Review this thoroughly as currently it depends on
        # parameters which is side-effecty.
        self.host = self.deploy()

        fabric_config = self.config.copy()
        fabric_config["run"]["env"] = {  # type: ignore
            # Set PATH since it’s not a login shell.
            "PATH": "/sbin:/usr/sbin:/usr/local/sbin:/bin:/usr/bin:/usr/local/bin"
        }
        self.conn = fabric.Connection(
            self.host,
            config=fabric.Config(overrides=fabric_config),
            inline_ssh_env=True,
        )

    # NOTE: This ought to be a property, but the combination of
    # @classmethod, @property, and @abstractmethod is only supported
    # in Python 3.9 and up.
    @classmethod
    @abstractmethod
    def schema(cls) -> Mapping[Any, Any]:
        """Must return a mapping for expected instance parameters.

        The items in this mapping are added to the playbook schema, so
        they may container objects from the `schema` library. Each
        target in the playbook will have `name` and `platform` keys in
        addition to those specified here (they're merged).

        """
        ...

    @abstractmethod
    def deploy(self) -> str:
        """Must deploy the target resources and return hostname."""
        ...

    @abstractmethod
    def delete(self) -> None:
        """Must delete the target resources."""
        ...

    # A class attribute because it’s defined.
    local_context = invoke.Context(config=invoke.Config(overrides=config))

    @classmethod
    def local(cls, *args: Any, **kwargs: Any) -> Result:
        """This patches Fabric's 'local()' function to ignore SSH environment."""
        return Target.local_context.run(*args, **kwargs)

    @retry(reraise=True, wait=wait_exponential(), stop=stop_after_attempt(3))
    def ping(self, **kwargs: Any) -> Result:
        """Ping the node from the local system in a cross-platform manner."""
        flag = "-c 1" if platform.system() == "Linux" else "-n 1"
        return self.local(f"ping {flag} {self.host}", **kwargs)

    def cat(self, path: str) -> str:
        """Gets the value of a remote file without a temporary file."""
        with BytesIO() as buf:
            self.conn.get(path, buf)
            return buf.getvalue().decode("utf-8").strip()


class SSH(Target):
    """The `SSH` platform simply connects to existing targets.

    It does not deploy nor delete the target. The default ``host`` is
    ``localhost`` so this can be used for testing against the user's
    system (if SSH is enabled).

    """

    @classmethod
    def schema(cls) -> Mapping[Any, Any]:
        return {
            schema.Optional(
                "host",
                default="localhost",
                description="The address of the destination target.",
            ): str
        }

    def deploy(self) -> str:
        return self.params["host"]

    def delete(self) -> None:
        pass
