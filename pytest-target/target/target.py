"""Provides the abstract base `Target` class."""
from __future__ import annotations

import platform
import typing
from abc import ABC, abstractmethod
from io import BytesIO

import fabric  # type: ignore
import invoke  # type: ignore
from invoke.runners import Result  # type: ignore
from schema import Literal, Optional, Schema  # type: ignore
from tenacity import retry, stop_after_attempt, wait_exponential  # type: ignore

if typing.TYPE_CHECKING:
    from typing import Any, Dict, Mapping, Set, Tuple


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
    group: str
    params: Mapping[str, str]
    features: Set[str]
    data: Mapping[Any, Any]
    number: int
    free: bool
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
        group: str,
        params: Mapping[Any, Any],
        features: Set[str],
        data: Mapping[Any, Any],
        number: int = 0,
        free: bool = False,
    ):
        """Creates and deploys an instance of `Target`.

        * `group` is a unique ID for the group of associated resources
        * `params` is the input parameters conforming to `schema()`
        * `features` is set of arbitrary feature requirements
        * `data` is the cached data for the target
        * `number` is the numerical ID of this target in its group
        * `free` is the state of the target in this session

        Subclass implementations of `Target` do not need to (and
        should not) override `__init__()` as it is setup such that all
        platform-specific setup logic can be encoded in `deploy()`
        instead, which this calls.

        """
        self.group = group
        self.params = self.get_schema().validate(params)
        self.features = features
        self.data = data
        self.number = number
        self.free = free

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
        they may contain objects from the `schema` library. Each
        target in the playbook will have `name` and `platform` keys in
        addition to those specified here (they're merged). Parameters
        should generally be `schema.Optional`. If the parameter should
        have a shared but mutable default value, set it in `defaults`.

        """
        ...

    @classmethod
    def defaults(cls) -> Mapping[Any, Any]:
        """Can return a mapping for default parameters.

        If specified, it must contain only `schema.Optional` elements,
        where the names and types match those in `schema()`, but with
        a set default value, and those in `schema()` should not
        contain default values. This is used a base for each target.

        """
        return {}

    @abstractmethod
    def deploy(self) -> str:
        """Must deploy the target resources and return the hostname.

        Subclass implementations can treat this like `__init__` with
        `schema()` defining the input `params`.

        Data which should be cached must be saved to `self.data`.

        If `self.data` is populated then implementations should assume
        they're refreshing a cached target.

        """
        ...

    @abstractmethod
    def delete(self) -> None:
        """Must delete the target's resources.

        If this is the last target in its group then implementations
        should delete the group resource too.

        """
        ...

    platform_description = "The class name of the platform implementation."

    @classmethod
    def get_defaults(cls) -> Tuple[Optional, Schema]:
        """Returns a tuple of "platform key" / "defaults value" pairs.

        This is an internal detail, used when generating the
        playbook's schema. Subclasses should not override this.

        The key is an optional literal, the name of the subclass for
        the platform, with a default value of the validated
        `defaults()` schema when given no input (hence they must all
        be optional). The value is reference schema definition
        generated from the `defaults()` dict.

        When generating the playbook's schema all the platforms'
        tuples are mapped into a single dict.

        TODO: Assert that the set of key names in each `defaults()` is
        a subset of the key names in the corresponding `schema()`.

        """
        return (
            Optional(
                cls.__name__,
                default=Schema(cls.defaults()).validate({}),
                description=cls.platform_description,
            ),
            Schema(cls.defaults(), name=f"{cls.__name__}_Defaults", as_reference=True),
        )

    @classmethod
    def get_schema(cls) -> Schema:
        """Returns a reference schema definition for the class parameters.

        This is an internal detail, used when generating the
        playbook's schema. Subclasses should not override this.

        We generate the whole definition by combining the values of
        `cls.schema()` (which is defined by each platform's
        implementation) with two required keys:

        * name: A friendly name for the target.
        * platform: The name of the subclass for the platform.

        When generating the playbook's schema all the platforms'
        schemata are mapped into an 'any of' schema.

        TODO: Perhaps elevate ‘name’ to the key, with the nested
        schema as the value.

        """
        return Schema(
            {
                # We’re adding ‘name’ and ‘platform’ keys.
                Literal("name", description="A friendly name for the target."): str,
                Literal("platform", description=cls.platform_description): cls.__name__,
                # Unpack the rest of the schema’s items.
                **cls.schema(),
            },
            name=f"{cls.__name__}_Schema",
            as_reference=True,
        )

    # Platform-agnostic functionality should be added here:

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
    def schema(cls) -> Dict[Any, Any]:
        return {
            Optional("host", description="The address of the destination target."): str
        }

    @classmethod
    def defaults(cls) -> Dict[Any, Any]:
        return {
            Optional(
                "host", default="localhost", description="The default value for host."
            ): str
        }

    def deploy(self) -> str:
        return self.params["host"]

    def delete(self) -> None:
        pass
