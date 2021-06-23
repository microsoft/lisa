# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import copy
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Type, TypeVar, Union, cast

from dataclasses_json import (
    CatchAll,
    DataClassJsonMixin,
    Undefined,
    config,
    dataclass_json,
)
from marshmallow import ValidationError, fields, validate

from lisa import search_space
from lisa.secret import PATTERN_HEADTAIL, add_secret
from lisa.util import BaseClassMixin, LisaException, constants

"""
Schema is dealt with three components,
1. dataclasses. It's a builtin class, uses to define schema of an instance. field()
   function uses to describe a field.
2. dataclasses_json. Serializer. config() function customizes this component.
3. marshmallow. Validator. It's wrapped by dataclasses_json. config(mm_field=xxx)
   function customizes this component.
"""


T = TypeVar("T")
keep_env_keys = Enum("keep_env_keys", ["no", "always", "failed"])


def metadata(
    field_function: Optional[Callable[..., Any]] = None, *args: Any, **kwargs: Any
) -> Any:
    """
    wrap for shorter
    """
    if field_function is None:
        field_function = fields.Raw
    assert field_function
    encoder = kwargs.pop("encoder", None)
    decoder = kwargs.pop("decoder", None)
    # keep data_key for underlying marshmallow
    field_name = kwargs.get("data_key")
    return config(
        field_name=cast(str, field_name),
        encoder=encoder,
        decoder=decoder,
        mm_field=field_function(*args, **kwargs),
    )


class ListableValidator(validate.Validator):
    default_message = ""

    def __init__(
        self,
        value_type: type,
        value_validator: Optional[
            Union[validate.Validator, List[validate.Validator]]
        ] = None,
        error: str = "",
    ) -> None:
        self._value_type: Any = value_type
        if value_validator is None:
            self._inner_validator: List[validate.Validator] = []
        elif callable(value_validator):
            self._inner_validator = [value_validator]
        elif isinstance(value_validator, list):
            self._inner_validator = list(value_validator)
        else:
            raise ValueError(
                "The 'value_validator' parameter must be a callable "
                "or a collection of callables."
            )
        self.error: str = error or self.default_message

    def _repr_args(self) -> str:
        return f"_inner_validator={self._inner_validator}"

    def _format_error(self, value: Any) -> str:
        return self.error.format(input=value)

    def __call__(self, value: Any) -> Any:
        if isinstance(value, self._value_type):
            if self._inner_validator:
                for validator in self._inner_validator:
                    validator(value)
        elif isinstance(value, list):
            for value_item in value:
                assert isinstance(value_item, self._value_type), (
                    f"must be '{self._value_type}' but '{value_item}' "
                    f"is '{type(value_item)}'"
                )
                if self._inner_validator:
                    for validator in self._inner_validator:
                        validator(value_item)
        elif value is not None:
            raise ValidationError(
                f"must be Union[{self._value_type}, List[{self._value_type}]], "
                f"but '{value}' is '{type(value)}'"
            )
        return value


@dataclass_json(undefined=Undefined.INCLUDE)
@dataclass
class ExtendableSchemaMixin:
    extended_schemas: CatchAll = field(default_factory=dict)  # type: ignore

    def get_extended_runbook(self, runbook_type: Type[T], type_name: str = "") -> T:
        """
        runbook_type: type of runbook
        field_name: the field name which stores the data, if it's "", get it from type
        """
        if not hasattr(self, "_extended_runbook"):
            type_name = self.__resolve_type_name(
                runbook_type=runbook_type, type_name=type_name
            )
            if self.extended_schemas and type_name in self.extended_schemas:
                self._extended_runbook: T = runbook_type.schema().load(  # type:ignore
                    self.extended_schemas[type_name]
                )
            else:
                # value may be filled outside, so hold and return an object.
                self._extended_runbook = runbook_type()

            # if there is any extra key, raise exception to help user find it earlier.
            if self.extended_schemas and len(self.extended_schemas) > 0:
                expected_extra_count = 0
                if type_name in self.extended_schemas:
                    expected_extra_count = 1
                if len(self.extended_schemas) > expected_extra_count:
                    extra_names = [
                        name for name in self.extended_schemas if name != type_name
                    ]
                    raise LisaException(
                        f"unknown keys in extendable schema [{runbook_type.__name__}]: "
                        f"{extra_names}"
                    )

        return self._extended_runbook

    def set_extended_runbook(self, runbook: Any, type_name: str = "") -> None:
        self._extended_runbook = runbook
        if self.extended_schemas and type_name in self.extended_schemas:
            # save extended runbook back to raw dict
            self.extended_schemas[type_name] = runbook.to_dict()

    def __resolve_type_name(self, runbook_type: Type[Any], type_name: str) -> str:
        assert issubclass(
            runbook_type, DataClassJsonMixin
        ), "runbook_type must annotate from DataClassJsonMixin"
        if not type_name:
            assert hasattr(self, constants.TYPE), (
                f"cannot find type attr on '{runbook_type.__name__}'."
                f"either set field_name or make sure type attr exists."
            )
            type_name = getattr(self, constants.TYPE)
        return type_name

    def __repr__(self) -> str:
        result = ""
        if hasattr(self, "_extended_runbook"):
            result = f"ext:{self._extended_runbook}"
        elif self.extended_schemas:
            result = f"ext:{self.extended_schemas}"
        return result


@dataclass_json()
@dataclass
class TypedSchema:
    type: str = ""


@dataclass_json(undefined=Undefined.INCLUDE)
@dataclass
class Combinator(TypedSchema):
    type: str = field(
        default=constants.COMBINATOR_GRID, metadata=metadata(required=True)
    )

    delay_parsed: CatchAll = field(default_factory=dict)  # type: ignore


@dataclass_json()
@dataclass
class Strategy:
    """
    node_path is the path of yaml node. For example:
        environment.nodes
    if node_path doesn't present, it means to all.

    operations include:
    overwrite: default behavior. add non-exist items and replace exist.
    remove: remove specified path totally.
    add: add non-exist, not replace exist.
    """

    node_path: str = field(default="", metadata=metadata(required=True))
    operation: str = field(
        default=constants.OPERATION_OVERWRITE,
        metadata=metadata(
            required=True,
            validate=validate.OneOf(
                [
                    constants.OPERATION_ADD,
                    constants.OPERATION_OVERWRITE,
                    constants.OPERATION_REMOVE,
                ]
            ),
        ),
    )


@dataclass_json()
@dataclass
class Parent:
    """
    share runbook for similar runs.
    """

    path: str = field(default="", metadata=metadata(required=True))
    strategy: Union[List[Strategy], Strategy, None] = None


@dataclass_json()
@dataclass
class Extension:
    path: str
    name: Optional[str] = None

    @classmethod
    def from_raw(cls, raw_data: Any) -> List["Extension"]:
        results: List[Extension] = []

        assert isinstance(raw_data, list), f"actual: {type(raw_data)}"
        for extension in raw_data:
            # convert to structured Extension
            if isinstance(extension, str):
                extension = Extension(path=extension)
            elif isinstance(extension, dict):
                extension = Extension.schema().load(extension)  # type: ignore
            results.append(extension)

        return results


@dataclass_json()
@dataclass
class VariableEntry:
    value: Union[str, bool, int] = ""
    is_secret: bool = False
    # True means this variable can be used in test cases.
    is_case_visible: bool = False
    mask: str = ""


@dataclass_json()
@dataclass
class Variable:
    """
    it uses to support variables in other fields.
    duplicate items will be overwritten one by one.
    if a variable is not defined here, LISA can fail earlier to ask check it.
    file path is relative to LISA command starts.
    """

    # If it's secret, it will be removed from log and other output information.
    # secret files also need to be removed after test
    # it's not recommended highly to put secret in runbook directly.
    is_secret: bool = False

    # continue to support v2 format. it's simple.
    file: str = field(
        default="",
        metadata=metadata(
            validate=validate.Regexp(r"([\w\W]+[.](xml|yml|yaml)$)|(^$)")
        ),
    )

    name: str = field(default="")
    value_raw: Union[str, bool, int, Dict[Any, Any], List[Any]] = field(
        default="", metadata=metadata(data_key="value")
    )
    # True means this variable can be used in test cases.
    is_case_visible: bool = False

    def __post_init__(self, *args: Any, **kwargs: Any) -> None:
        if self.file and (self.name or self.value_raw):
            raise LisaException(
                f"file cannot be specified with name or value"
                f"file: '{self.file}'"
                f"name: '{self.name}'"
                f"value: '{self.value_raw}'"
            )

        if isinstance(self.value_raw, dict):
            self.value: Union[
                str, bool, int, VariableEntry, List[Union[str, bool, int]]
            ] = cast(
                VariableEntry,
                VariableEntry.schema().load(self.value_raw),  # type:ignore
            )
        else:
            self.value = self.value_raw


@dataclass_json(undefined=Undefined.INCLUDE)
@dataclass
class Notifier(TypedSchema):
    """
    it sends test progress and results to any place wanted.
    detail types are defined in notifier itself, allowed items are handled in code.
    """

    delay_parsed: CatchAll = field(default_factory=dict)  # type: ignore


@dataclass_json(undefined=Undefined.INCLUDE)
@dataclass
class NodeSpace(search_space.RequirementMixin, TypedSchema, ExtendableSchemaMixin):
    type: str = field(
        default=constants.ENVIRONMENTS_NODES_REQUIREMENT,
        metadata=metadata(
            required=True,
            validate=validate.OneOf([constants.ENVIRONMENTS_NODES_REQUIREMENT]),
        ),
    )
    name: str = ""
    is_default: bool = field(default=False)
    node_count: search_space.CountSpace = field(
        default=search_space.IntRange(min=1),
        metadata=metadata(decoder=search_space.decode_count_space),
    )
    core_count: search_space.CountSpace = field(
        default=search_space.IntRange(min=1),
        metadata=metadata(decoder=search_space.decode_count_space),
    )
    memory_mb: search_space.CountSpace = field(
        default=search_space.IntRange(min=512),
        metadata=metadata(decoder=search_space.decode_count_space),
    )
    disk_count: search_space.CountSpace = field(
        default=search_space.IntRange(min=1),
        metadata=metadata(decoder=search_space.decode_count_space),
    )
    nic_count: search_space.CountSpace = field(
        default=search_space.IntRange(min=1),
        metadata=metadata(decoder=search_space.decode_count_space),
    )
    gpu_count: search_space.CountSpace = field(
        default=search_space.IntRange(min=0),
        metadata=metadata(decoder=search_space.decode_count_space),
    )
    # all features on requirement should be included.
    # all features on capability can be included.
    features: Optional[search_space.SetSpace[str]] = field(
        default=None,
        metadata=metadata(
            decoder=search_space.decode_set_space,
            allow_none=True,
        ),
    )
    # set by requirements
    # capability's is ignored
    excluded_features: Optional[search_space.SetSpace[str]] = field(
        default=None,
        metadata=metadata(
            decoder=search_space.decode_set_space,
            allow_none=True,
        ),
    )

    def __post_init__(self, *args: Any, **kwargs: Any) -> None:
        if self.features is not None:
            self.features.is_allow_set = True
        if self.excluded_features is not None:
            self.excluded_features.is_allow_set = False

    def __eq__(self, o: object) -> bool:
        assert isinstance(o, NodeSpace), f"actual: {type(o)}"
        return (
            self.type == o.type
            and self.node_count == o.node_count
            and self.core_count == o.core_count
            and self.memory_mb == o.memory_mb
            and self.disk_count == o.disk_count
            and self.nic_count == o.nic_count
            and self.gpu_count == o.gpu_count
            and self.features == o.features
            and self.excluded_features == o.excluded_features
        )

    def __repr__(self) -> str:
        """
        override it for shorter text
        """
        return (
            f"type:{self.type},name:{self.name},"
            f"default:{self.is_default},"
            f"count:{self.node_count},core:{self.core_count},"
            f"mem:{self.memory_mb},disk:{self.disk_count},"
            f"nic:{self.nic_count},gpu:{self.gpu_count},"
            f"f:{self.features},ef:{self.excluded_features},"
            f"{super().__repr__()}"
        )

    def check(self, capability: Any) -> search_space.ResultReason:
        result = search_space.ResultReason()
        if capability is None:
            result.add_reason("capability shouldn't be None")

        if self.features:
            assert self.features.is_allow_set, "features should be allow set"
        if self.excluded_features:
            assert (
                not self.excluded_features.is_allow_set
            ), "excluded_features shouldn't be allow set"

        assert isinstance(capability, NodeSpace), f"actual: {type(capability)}"

        if (
            not capability.node_count
            or not capability.core_count
            or not capability.memory_mb
            or not capability.disk_count
            or not capability.nic_count
        ):
            result.add_reason(
                "node_count, core_count, memory_mb, disk_count, nic_count "
                "shouldn't be None or zero."
            )

        if isinstance(self.node_count, int) and isinstance(capability.node_count, int):
            if self.node_count > capability.node_count:
                result.add_reason(
                    f"capability node count {capability.node_count} "
                    f"must be more than requirement {self.node_count}"
                )
        else:
            result.merge(
                search_space.check_countspace(self.node_count, capability.node_count),
                "node_count",
            )

        result.merge(
            search_space.check_countspace(self.core_count, capability.core_count),
            "core_count",
        )
        result.merge(
            search_space.check_countspace(self.memory_mb, capability.memory_mb),
            "memory_mb",
        )
        result.merge(
            search_space.check_countspace(self.disk_count, capability.disk_count),
            "disk_count",
        )
        result.merge(
            search_space.check_countspace(self.nic_count, capability.nic_count),
            "nic_count",
        )
        result.merge(
            search_space.check_countspace(self.gpu_count, capability.gpu_count),
            "gpu_count",
        )
        result.merge(
            search_space.check(self.features, capability.features),
            "features",
        )
        if self.excluded_features:
            result.merge(
                self.excluded_features.check(capability.features),
                "excluded_features",
            )

        return result

    def expand_by_node_count(self) -> List[Any]:
        # expand node count in requirement to one,
        # so that's easy to compare equalization later.
        expanded_requirements: List[NodeSpace] = []
        node_count = search_space.generate_min_capability_countspace(
            self.node_count, self.node_count
        )
        for _ in range(node_count):
            expanded_copy = copy.copy(self)
            expanded_copy.node_count = 1
            expanded_requirements.append(expanded_copy)
        return expanded_requirements

    def _generate_min_capability(self, capability: Any) -> Any:
        # copy to duplicate extended schema
        min_value: NodeSpace = copy.deepcopy(self)
        assert isinstance(capability, NodeSpace), f"actual: {type(capability)}"

        if self.node_count or capability.node_count:
            if isinstance(self.node_count, int) and isinstance(
                capability.node_count, int
            ):
                # capability can have more node
                min_value.node_count = capability.node_count
            else:
                min_value.node_count = search_space.generate_min_capability_countspace(
                    self.node_count, capability.node_count
                )
        else:
            raise LisaException("node_count cannot be zero")
        if self.core_count or capability.core_count:
            min_value.core_count = search_space.generate_min_capability_countspace(
                self.core_count, capability.core_count
            )
        else:
            raise LisaException("core_count cannot be zero")
        if self.memory_mb or capability.memory_mb:
            min_value.memory_mb = search_space.generate_min_capability_countspace(
                self.memory_mb, capability.memory_mb
            )
        else:
            raise LisaException("memory_mb cannot be zero")
        if self.disk_count or capability.disk_count:
            min_value.disk_count = search_space.generate_min_capability_countspace(
                self.disk_count, capability.disk_count
            )
        else:
            raise LisaException("disk_count cannot be zero")
        if self.nic_count or capability.nic_count:
            min_value.nic_count = search_space.generate_min_capability_countspace(
                self.nic_count, capability.nic_count
            )
        else:
            raise LisaException("nic_count cannot be zero")
        if self.gpu_count or capability.gpu_count:
            min_value.gpu_count = search_space.generate_min_capability_countspace(
                self.gpu_count, capability.gpu_count
            )
        else:
            min_value.gpu_count = 0

        if capability.features:
            min_value.features = search_space.SetSpace[str](is_allow_set=True)
            min_value.features.update(capability.features)
        if capability.excluded_features:
            min_value.excluded_features = search_space.SetSpace[str](is_allow_set=False)
            min_value.excluded_features.update(capability.excluded_features)
        return min_value


@dataclass_json()
@dataclass
class Capability(NodeSpace):
    type: str = constants.ENVIRONMENTS_NODES_REQUIREMENT

    def __post_init__(self, *args: Any, **kwargs: Any) -> None:
        super().__post_init__(*args, **kwargs)
        self.node_count = 1


@dataclass_json(undefined=Undefined.INCLUDE)
@dataclass
class Node(TypedSchema):
    type: str
    capability: Capability = field(default_factory=Capability)
    name: str = ""
    is_default: bool = field(default=False)

    delay_parsed: CatchAll = field(default_factory=dict)  # type: ignore


@dataclass_json()
@dataclass
class LocalNode(Node):
    type: str = constants.ENVIRONMENTS_NODES_LOCAL


@dataclass_json()
@dataclass
class RemoteNode(Node):
    type: str = constants.ENVIRONMENTS_NODES_REMOTE
    address: str = ""
    port: int = field(
        default=22,
        metadata=metadata(
            field_function=fields.Int, validate=validate.Range(min=1, max=65535)
        ),
    )
    public_address: str = ""
    public_port: int = field(
        default=22,
        metadata=metadata(
            field_function=fields.Int, validate=validate.Range(min=1, max=65535)
        ),
    )
    username: str = ""
    password: str = ""
    private_key_file: str = ""

    def __post_init__(self, *args: Any, **kwargs: Any) -> None:
        add_secret(self.username, PATTERN_HEADTAIL)
        add_secret(self.password)
        add_secret(self.private_key_file)


@dataclass_json()
@dataclass
class Environment:
    name: str = field(default="")
    topology: str = field(
        default=constants.ENVIRONMENTS_SUBNET,
        metadata=metadata(validate=validate.OneOf([constants.ENVIRONMENTS_SUBNET])),
    )
    nodes_raw: Optional[List[Any]] = field(
        default=None,
        metadata=metadata(data_key=constants.NODES),
    )
    nodes_requirement: Optional[List[NodeSpace]] = None

    def __post_init__(self, *args: Any, **kwargs: Any) -> None:
        results: List[Node] = []

        if self.nodes_raw:
            for node_raw in self.nodes_raw:
                node_type = node_raw[constants.TYPE]
                if node_type == constants.ENVIRONMENTS_NODES_REQUIREMENT:
                    original_req: NodeSpace = NodeSpace.schema().load(  # type:ignore
                        node_raw
                    )
                    expanded_req = original_req.expand_by_node_count()
                    if self.nodes_requirement is None:
                        self.nodes_requirement = []
                    self.nodes_requirement.extend(expanded_req)
                else:
                    # load base schema for future parsing
                    node: Node = Node.schema().load(  # type:ignore
                        node_raw
                    )
                    results.append(node)
            self.nodes_raw = None

        self.nodes = results


@dataclass_json()
@dataclass
class EnvironmentRoot:
    max_concurrency: int = field(
        default=1,
        metadata=metadata(field_function=fields.Int, validate=validate.Range(min=1)),
    )
    warn_as_error: bool = field(default=False)
    environments: List[Environment] = field(default_factory=list)


@dataclass_json(undefined=Undefined.INCLUDE)
@dataclass
class Platform(TypedSchema, ExtendableSchemaMixin):
    type: str = field(
        default=constants.PLATFORM_READY,
        metadata=metadata(required=True),
    )

    admin_username: str = "lisatest"
    admin_password: str = ""
    admin_private_key_file: str = ""

    # no/False: means to delete the environment regardless case fail or pass
    # yes/always/True: means to keep the environment regardless case fail or pass
    keep_environment: Optional[Union[str, bool]] = False

    # platform can specify a default environment requirement
    requirement: Optional[Dict[str, Any]] = None

    def __post_init__(self, *args: Any, **kwargs: Any) -> None:
        add_secret(self.admin_username, PATTERN_HEADTAIL)
        add_secret(self.admin_password)

        if self.type != constants.PLATFORM_READY:
            if self.admin_password and self.admin_private_key_file:
                raise LisaException(
                    "only one of admin_password and admin_private_key_file can be set"
                )
            elif not self.admin_password and not self.admin_private_key_file:
                raise LisaException(
                    "one of admin_password and admin_private_key_file must be set"
                )

        if isinstance(self.keep_environment, str):
            self.keep_environment = self.keep_environment.lower()
            allow_list = [x for x in keep_env_keys.__members__.keys()]
            if self.keep_environment not in allow_list:
                raise LisaException(
                    f"keep_environment only can be set as one of {allow_list}"
                )

        # this requirement in platform will be applied to each test case
        # requirement. It means the set value will override value in test cases.
        # But the schema will be validated here. The original NodeSpace object holds
        if self.requirement:
            # validate schema of raw inputs
            Capability.schema().load(self.requirement)  # type: ignore


@dataclass_json()
@dataclass
class Criteria:
    """
    all rules in same criteria are AND condition.
    we may support richer conditions later.
    match case by name pattern
    """

    name: Optional[str] = None
    area: Optional[str] = None
    category: Optional[str] = None
    # the runbook is complex to convert, so manual overwrite it in __post_init__.
    priority: Optional[Union[int, List[int]]] = field(
        default=None,
        metadata=metadata(
            validate=ListableValidator(int, validate.Range(min=0, max=4))
        ),
    )
    # tags is a simple way to include test cases within same topic.
    tags: Optional[Union[str, List[str]]] = field(
        default=None, metadata=metadata(validate=ListableValidator(str))
    )


@dataclass_json(undefined=Undefined.INCLUDE)
@dataclass
class BaseTestCaseFilter(TypedSchema, BaseClassMixin):
    """
    base test case filters for subclass factory
    """

    type: str = field(
        default=constants.TESTCASE_TYPE_LISA,
    )
    # if it's false, current filter is ineffective.
    enable: bool = field(default=True)

    mismatched: CatchAll = field(default_factory=dict)  # type: ignore


@dataclass_json()
@dataclass
class TestCase(BaseTestCaseFilter):
    type: str = field(
        default=constants.TESTCASE_TYPE_LISA,
        metadata=metadata(
            validate=validate.OneOf([constants.TESTCASE_TYPE_LISA]),
        ),
    )
    name: str = ""
    criteria: Optional[Criteria] = None
    # specify use this rule to select or drop test cases. if it's forced include or
    # exclude, it won't be effect by following select actions. And it fails if
    # there are force rules conflict.
    select_action: str = field(
        default=constants.TESTCASE_SELECT_ACTION_INCLUDE,
        metadata=config(
            mm_field=fields.String(
                validate=validate.OneOf(
                    [
                        # none means this action part doesn't include or exclude cases
                        constants.TESTCASE_SELECT_ACTION_NONE,
                        constants.TESTCASE_SELECT_ACTION_INCLUDE,
                        constants.TESTCASE_SELECT_ACTION_FORCE_INCLUDE,
                        constants.TESTCASE_SELECT_ACTION_EXCLUDE,
                        constants.TESTCASE_SELECT_ACTION_FORCE_EXCLUDE,
                    ]
                )
            ),
        ),
    )
    # run this group of test cases several times
    # default is 1
    times: int = field(
        default=1,
        metadata=metadata(field_function=fields.Int, validate=validate.Range(min=1)),
    )
    # retry times if fails. Default is 0, not to retry.
    retry: int = field(
        default=0,
        metadata=metadata(field_function=fields.Int, validate=validate.Range(min=0)),
    )
    # each case with this rule will be run in a new environment.
    use_new_environment: bool = False
    # Once it's set, failed test result will be rewrite to success
    # it uses to work around some cases temporarily, don't overuse it.
    # default is false
    ignore_failure: bool = False
    # case should run on a specified environment
    environment: str = ""

    @classmethod
    def type_name(cls) -> str:
        return constants.TESTCASE_TYPE_LISA


@dataclass_json()
@dataclass
class LegacyTestCase(BaseTestCaseFilter):
    type: str = field(
        default=constants.TESTCASE_TYPE_LEGACY,
        metadata=metadata(
            required=True,
            validate=validate.OneOf([constants.TESTCASE_TYPE_LEGACY]),
        ),
    )

    repo: str = "https://github.com/microsoft/lisa.git"
    branch: str = "master"
    command: str = ""

    @classmethod
    def type_name(cls) -> str:
        return constants.TESTCASE_TYPE_LEGACY


@dataclass_json()
@dataclass
class Runbook:
    # run name prefix to help grouping results and put it in title.
    name: str = "not_named"
    test_project: str = ""
    test_pass: str = ""
    tags: Optional[List[str]] = None
    concurrency: int = 1
    parent: Optional[List[Parent]] = field(default=None)
    extension: Optional[List[Union[str, Extension]]] = field(default=None)
    variable: Optional[List[Variable]] = field(default=None)
    combinator: Optional[Combinator] = field(default=None)
    environment: Optional[EnvironmentRoot] = field(default=None)
    notifier: Optional[List[Notifier]] = field(default=None)
    platform: List[Platform] = field(default_factory=list)
    #  will be parsed in runner.
    testcase_raw: List[Any] = field(
        default_factory=list, metadata=metadata(data_key=constants.TESTCASE)
    )

    def __post_init__(self, *args: Any, **kwargs: Any) -> None:
        if not self.platform:
            self.platform = [Platform(type=constants.PLATFORM_READY)]
        if not self.testcase_raw:
            self.testcase_raw = [
                {
                    constants.TESTCASE_CRITERIA: {
                        constants.TESTCASE_CRITERIA_AREA: "demo"
                    }
                }
            ]
        self.testcase: List[Any] = []
