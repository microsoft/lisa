# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Provides the abstract base :py:class:`~target.target.Target` class.

This abstract base class provides the building blocks for any platform
support that could be required. Users simply define a subclass with
the abstract methods implemented to deploy or delete the target
appropriately.

"""
from __future__ import annotations

import dataclasses
import platform
import typing
import warnings
from abc import ABCMeta, abstractmethod
from io import BytesIO

import fabric  # type: ignore
import invoke  # type: ignore
from invoke.runners import Result  # type: ignore
from schema import Literal, Optional, Schema  # type: ignore
from tenacity import (  # type: ignore
    retry,
    retry_if_result,
    stop_after_attempt,
    wait_exponential,
)

if typing.TYPE_CHECKING:
    from typing import Any, Dict, List, Mapping, Tuple, Type


@dataclasses.dataclass
class TargetData:
    """This class holds serializable data for a :py:class:`Target`.

    This is an internal detail. It is separated out so we can easily
    serialize to and from JSON in order to enable caching. By
    decoupling these we prevent users from having to understand the
    semantics of a ``dataclass``, and fields added to subclasses don't
    interfere with serialization.

    .. TODO::

       Consider using more from ``dataclasses``, such as ``field()``
       and ``__post_init__()``.

    """

    group: str
    params: Dict[str, str]
    features: List[str]
    data: Dict[Any, Any]
    number: int
    locked: bool

    def to_json(self) -> Dict[str, Any]:
        """Returns a JSON-serializable representation of the ``Target``."""
        return dataclasses.asdict(self)

    @staticmethod
    def from_json(json: Dict[str, Any]) -> Target:
        """Instantiates the correct ``Target`` subclass given the JSON representation."""
        cls = Target.get_platform(json["params"]["platform"])
        return cls(**json)


class Target(TargetData, metaclass=ABCMeta):
    """This class represents a remote Linux target.

    As a partially abstract base class, it is meant to be subclassed
    to provide platform support. So ``Target`` as a class maps to the
    concept of a Linux target machine reachable via SSH (through
    :py:attr:`conn`, an instance of `Fabric.Connection`_). Each
    subclass of ``Target`` provides the necessary implementation to
    instantiate an actual Linux target, by deploying it on that
    platform. Each _instance_ of a platform-specific subclass of
    ``Target`` maps to an actual Linux target that has been deployed
    on that platform.

    .. _Fabric.Connection: https://docs.fabfile.org/en/stable/api/connection.html

    """

    # Typed instance attributes (not class attributes) in addition to
    # those inherited from the dataclass `TargetData`. These exist
    # here and not on the superclass because they shouldn’t be cached.
    name: str
    host: str
    conn: fabric.Connection
    """Used for SSH access, see `Fabric.Connection`_"""

    # Setup a sane configuration for local and remote commands. Note
    # that the defaults between Fabric and Invoke are different, so we
    # use their Config classes explicitly later.
    _config = {
        "run": {
            # Show each command as its run.
            "echo": True,
            # Disable stdin forwarding.
            "in_stream": False,
            # Don’t let remote commands take longer than twenty minutes
            # (unless later overridden). This is to prevent hangs.
            "command_timeout": 1200,
        }
    }

    def __init__(
        self,
        group: str,
        params: Dict[Any, Any],
        features: List[str],
        data: Dict[Any, Any],
        number: int = 0,
        locked: bool = True,
    ):
        """Creates and deploys an instance of :py:class:`Target`.

        :param group: is a unique ID for the group of associated resources
        :param params: is the input parameters conforming to `schema()`
        :param features: is set of arbitrary feature requirements
        :param data: is the cached data for the target
        :param number: is the numerical ID of this target in its group
        :param locked: is the state of the target's availability

        Subclass implementations of ``Target`` do not need to (and
        should not) override :py:meth:`__init__` as it is setup such
        that all platform-specific setup logic can be encoded in
        :py:meth:`deploy` instead, which this calls.

        """
        self.group = group
        self.params = self.get_schema().validate(params)
        self.features = features
        self.data = data
        self.number = number
        self.locked = locked
        self.name = f"{self.group}-{self.number}"

        try:
            self.host = self.deploy()
        except Exception as e:
            warnings.warn(f"Failed to deploy '{self.name}': {e}")

        fabric_config = self._config.copy()
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
        they may contain objects from the `schema`_ library. Each
        target in the playbook will have ``name`` and ``platform``
        keys in addition to those specified here (they're merged).
        Parameters should generally be ``schema.Optional``. If the
        parameter should have a shared but mutable default value, set
        it in ``defaults``.

        .. _schema: https://github.com/keleshev/schema

        """
        ...

    @classmethod
    def defaults(cls) -> Mapping[Any, Any]:
        """Can return a mapping for default parameters.

        If specified, it must contain only ``schema.Optional``
        elements, where the names and types match those in
        :py:meth:`schema`, but with a set default value, and those in
        :py:meth:`schema` should not contain default values. This is
        used a base for each target.

        """
        return {}

    @abstractmethod
    def deploy(self) -> str:
        """Must deploy the target resources and return the hostname.

        Subclass implementations can treat this like ``__init__`` with
        :py:meth:`schema` defining the input ``params``.

        Data which should be cached must be saved to :py:attr:`data`.

        If :py:attr:`data` is populated then implementations should
        assume they're refreshing a cached target.

        """
        ...

    @abstractmethod
    def delete(self) -> None:
        """Must delete the target's resources.

        If this is the last target in its group then implementations
        should delete the group resource too.

        """
        ...

    # Internal details follow:

    _platform_description = "The class name of the platform implementation."

    @classmethod
    def get_defaults(cls) -> Tuple[Optional, Schema]:
        """Returns a tuple of "platform key" / "defaults value" pairs.

        This is an internal detail, used when generating the
        playbook's schema. Subclasses should not override this.

        The key is an optional literal, the name of the subclass for
        the platform, with a default value of the validated
        :py:meth:`defaults` schema when given no input (hence they
        must all be optional). The value is reference schema
        definition generated from the :py:meth:`defaults` dict.

        When generating the playbook's schema all the platforms'
        tuples are mapped into a single dict.

        .. TODO::

           Assert that the set of key names in each ``defaults()`` is
           a subset of the key names in the corresponding
           ``schema()``.

        """
        return (
            Optional(
                cls.__name__,
                default=Schema(cls.defaults()).validate({}),
                description=cls._platform_description,
            ),
            Schema(cls.defaults(), name=f"{cls.__name__}_Defaults", as_reference=True),
        )

    @classmethod
    def get_schema(cls) -> Schema:
        """Returns a reference schema definition for the class parameters.

        This is an internal detail, used when generating the
        playbook's schema. Subclasses should not override this.

        We generate the whole definition by combining the values of
        :py:meth:`schema` (which is defined by each platform's
        implementation) with two required keys:

        * ``name``: A friendly name for the target.
        * ``platform``: The name of the subclass for the platform.

        When generating the playbook's schema all the platforms'
        schemata are mapped into an 'any of' schema.

        .. TODO::

           Perhaps elevate ‘name’ to the key, with the nested schema
           as the value.

        """
        return Schema(
            {
                # We’re adding ‘name’ and ‘platform’ keys.
                Literal("name", description="A friendly name for the target."): str,
                Literal(
                    "platform", description=cls._platform_description
                ): cls.__name__,
                # Unpack the rest of the schema’s items.
                **cls.schema(),
            },
            name=f"{cls.__name__}_Schema",
            as_reference=True,
        )

    @staticmethod
    def get_platform(platform: str) -> Type[Target]:
        """Returns the :py:class:`Target` subclass for the named platform."""
        cls: typing.Optional[typing.Type[Target]] = next(
            (x for x in Target.__subclasses__() if x.__name__ == platform),
            None,
        )
        assert cls, f"Platform implementation not found for '{platform}'"
        return cls

    # Platform-agnostic functionality should be added here:

    _local_context = invoke.Context(config=invoke.Config(overrides=_config))

    @classmethod
    def local(cls, *args: Any, **kwargs: Any) -> Result:
        """This patches Fabric's ``local()`` function to ignore SSH environment."""
        return Target._local_context.run(*args, **kwargs)

    @retry(
        retry=retry_if_result(lambda result: result.failed),
        retry_error_callback=(lambda retry_state: retry_state.outcome.result()),
        wait=wait_exponential(),
        stop=stop_after_attempt(5),
    )
    def ping(self, **kwargs: Any) -> Result:
        """Ping the node from the local system in a cross-platform manner.

        This is setup such that it retries five times when the exit
        code is nonzero, with an exponential backoff. Since we want to
        return the command's result regardless of failure, we suppress
        `Invoke`_'s exception with ``warn=True`` and `Tenacity`_'s exception
        with ``retry_error_callback=...``.

        .. _Invoke: https://www.pyinvoke.org/
        .. _Tenacity: https://tenacity.readthedocs.io/en/latest/

        """
        flag = "-c 1" if platform.system() == "Linux" else "-n 1"
        return self.local(f"ping {flag} {self.host}", warn=True, **kwargs)

    def cat(self, path: str) -> str:
        """Gets the value of a remote file without a temporary file."""
        with BytesIO() as buf:
            self.conn.get(path, buf)
            return buf.getvalue().decode("utf-8").strip()


class SSH(Target):
    """This platform simply connects to existing targets.

    It does not deploy nor delete the target. The default ``host`` is
    ``localhost`` so this can be used for testing against the user's
    system (if SSH is enabled).

    """

    @classmethod
    def schema(cls) -> Dict[Any, Any]:
        """Takes a ``host`` parameter."""
        return {
            Optional("host", description="The address of the destination target."): str
        }

    @classmethod
    def defaults(cls) -> Dict[Any, Any]:
        """Defaults to ``localhost``."""
        return {
            Optional(
                "host", default="localhost", description="The default value for host."
            ): str
        }

    def deploy(self) -> str:
        return self.params["host"]

    def delete(self) -> None:
        pass
