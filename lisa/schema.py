from dataclasses import dataclass, field
from dataclasses import fields as dataclass_fields
from typing import Any, Callable, ClassVar, List, Optional, Type, TypeVar, Union

from dataclasses_json import (  # type: ignore
    DataClassJsonMixin,
    LetterCase,
    config,
    dataclass_json,
)
from marshmallow import fields, validate

from lisa.util import constants
from lisa.util.exceptions import LisaException

"""
Schema is dealt with three components,
1. dataclasses. It's a builtin class, uses to define schema of an instance. field()
   function uses to describe a field.
2. dataclasses_json. Serializer. config() function customizes this component.
3. marshmallow. Validator. It's wrapped by dataclasses_json. config(mm_field=xxx)
   function customizes this component.
"""


def metadata(
    field_function: Optional[Callable[..., Any]] = None, *args: Any, **kwargs: Any
) -> Any:
    """
    wrap for shorter
    """
    if field_function is None:
        field_function = fields.Raw
    assert field_function
    return config(mm_field=field_function(*args, **kwargs))


T = TypeVar("T", bound=DataClassJsonMixin)


class ExtendableSchemaMixin:
    def get_extended_schema(
        self, schema_type: Type[T], schema_name: str = constants.TYPE
    ) -> T:
        assert issubclass(
            schema_type, DataClassJsonMixin
        ), "schema_type must annotate from DataClassJsonMixin"
        assert hasattr(self, schema_name), f"cannot find attr '{schema_name}'"

        customized_config = getattr(self, schema_name)
        if not isinstance(customized_config, schema_type):
            raise LisaException(
                f"schema type mismatch, expected type: {schema_type}"
                f"data: {customized_config}"
            )
        return customized_config


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class Strategy:
    """
    for simple merge, this part is optional.
    operations include:
    overwrite: default behavior. add non-exist items and replace exist.
    remove: remove specified path totally.
    add: add non-exist, not replace exist.
    """

    path: str = field(default="", metadata=metadata(required=True))
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


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class Parent:
    """
    share configurations for similar runs.
    """

    path: str = field(default="", metadata=metadata(required=True))
    strategy: List[Strategy] = field(
        default_factory=list, metadata=metadata(required=True),
    )


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class Extension:
    """
    add extended classes can be put in folders and include here. it doesn't matter how
    those files are organized, lisa loads by their inherits relationship. if there is
    any conflict on type name, there should be an error message.
    """

    paths: List[str] = field(default_factory=list, metadata=metadata(required=True))


@dataclass_json(letter_case=LetterCase.CAMEL)
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
    # it's not recommended highly to put secret in configurations directly.
    is_secret: bool = False

    # continue to support v2 format. it's simple.
    file: str = field(
        default="",
        metadata=metadata(validate=validate.Regexp(r"[\w\W]+[.](xml|yml|yaml)$")),
    )

    name: str = field(default="")
    value: str = field(default="")

    def __post_init__(self, *args: Any, **kwargs: Any) -> None:
        if self.file and (self.name or self.value):
            raise LisaException(
                f"file cannot be specified with name or value"
                f"file: '{self.file}'"
                f"name: '{self.name}'"
                f"value: '{self.value}'"
            )


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class ArtifactLocation:
    type: str = field(
        default="", metadata=metadata(required=True, validate=validate.OneOf([])),
    )
    path: str = field(default="", metadata=metadata(required=True))


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class Artifact:
    # name is optional. artifacts can be referred by name or index.
    name: str = ""
    type: str = field(
        default="", metadata=metadata(required=True, validate=validate.OneOf([])),
    )
    locations: List[ArtifactLocation] = field(default_factory=list)


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class Notifier:
    """
    it sends test progress and results to any place wanted.
    detail types are defined in notifier itself, allowed items are handled in code.
    """

    type: str = field(
        default="", metadata=metadata(required=True, validate=validate.OneOf([])),
    )


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class LocalNode:
    type: str = field(
        default=constants.ENVIRONMENTS_NODES_LOCAL,
        metadata=metadata(
            required=True,
            validate=validate.OneOf([constants.ENVIRONMENTS_NODES_LOCAL]),
        ),
    )
    name: str = ""
    is_default: bool = field(default=False)


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class RemoteNode:
    type: str = field(
        default=constants.ENVIRONMENTS_NODES_REMOTE,
        metadata=metadata(
            required=True,
            validate=validate.OneOf([constants.ENVIRONMENTS_NODES_REMOTE]),
        ),
    )
    name: str = ""
    is_default: bool = field(default=False)
    address: str = ""
    port: int = field(
        default=1, metadata=metadata(validate=validate.Range(min=1, max=65535))
    )
    public_address: str = ""
    public_port: int = field(
        default=1,
        metadata=metadata(
            data_key="publicPort", validate=validate.Range(min=1, max=65535)
        ),
    )
    username: str = field(default="", metadata=metadata(required=True))
    password: str = ""
    private_key_file: str = ""

    def __post_init__(self, *args: Any, **kwargs: Any) -> None:
        if not self.address and not self.public_address:
            raise LisaException(
                "at least one of address and publicAddress need to be set"
            )
        elif not self.address:
            self.address = self.public_address
        elif not self.public_address:
            self.public_address = self.address

        if not self.port and not self.public_port:
            raise LisaException("at least one of port and publicPort need to be set")
        elif not self.port:
            self.port = self.public_port
        elif not self.public_port:
            self.public_port = self.port

        if not self.password and not self.private_key_file:
            raise LisaException(
                "at least one of password and privateKeyFile need to be set"
            )


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class NodeSpec(ExtendableSchemaMixin):
    type: str = field(
        default=constants.ENVIRONMENTS_NODES_SPEC,
        metadata=metadata(
            required=True, validate=validate.OneOf([constants.ENVIRONMENTS_NODES_SPEC]),
        ),
    )
    name: str = ""
    is_default: bool = field(default=False)
    # optional, if there is only one artifact.
    artifact: str = field(default="")
    cpu_count: int = field(
        default=1,
        metadata=metadata(data_key="cpuCount", validate=validate.Range(min=1)),
    )
    memory_gb: int = field(
        default=1,
        metadata=metadata(data_key="memoryGb", validate=validate.Range(min=1)),
    )
    gpu_count: int = field(
        default=0,
        metadata=metadata(data_key="gpuCount", validate=validate.Range(min=0)),
    )


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class Template(NodeSpec):
    node_count: int = field(
        default=1,
        metadata=metadata(data_key="nodeCount", validate=validate.Range(min=1)),
    )


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class Environment:
    name: str = field(default="")
    # the environment spec may not be fully supported by each platform.
    # If so, there is a warning message.
    # Environment spec can be forced to apply, as error is loud.
    topology: str = field(
        default=constants.ENVIRONMENTS_SUBNET,
        metadata=metadata(validate=validate.OneOf([constants.ENVIRONMENTS_SUBNET])),
    )
    # template and nodes conflicts, they should have only one.
    #  it uses to prevent duplicate content for big amount nodes.
    template: Optional[Template] = field(default=None)
    # field_name is a config level variable, so use config directly.
    _nodes_raw: Optional[List[Any]] = field(
        default=None, metadata=metadata(data_key=constants.NODES),
    )

    def __post_init__(self, *args: Any, **kwargs: Any) -> None:
        if self.template and self._nodes_raw:
            raise LisaException("cannot specify tempate and nodes both")
        if self._nodes_raw:
            # dataclasses_json cannot handle Union well, so manual handle it
            self.nodes: List[Union[NodeSpec, LocalNode, RemoteNode]] = []
            for node_raw in self._nodes_raw:
                if node_raw[constants.TYPE] == constants.ENVIRONMENTS_NODES_LOCAL:
                    node: Union[
                        NodeSpec, LocalNode, RemoteNode
                    ] = LocalNode.schema().load(  # type:ignore
                        node_raw
                    )
                elif node_raw[constants.TYPE] == constants.ENVIRONMENTS_NODES_REMOTE:
                    node = RemoteNode.schema().load(node_raw)  # type:ignore
                elif node_raw[constants.TYPE] == constants.ENVIRONMENTS_NODES_SPEC:
                    node = NodeSpec.schema().load(node_raw)  # type:ignore
                else:
                    raise LisaException(
                        f"unknown config type '{type(config)}': {config}"
                    )
                self.nodes.append(node)


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class EnvironmentRoot:
    max_concurrency: int = field(
        default=1,
        metadata=metadata(data_key="maxConcurrency", validate=validate.Range(min=1)),
    )
    warn_as_error: bool = field(default=False)
    environments: List[Environment] = field(default_factory=list)


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class Platform(ExtendableSchemaMixin):
    type: str = field(
        default=constants.PLATFORM_READY,
        metadata=metadata(
            required=True, validate=validate.OneOf([constants.PLATFORM_READY]),
        ),
    )

    supported_types: ClassVar[List[str]] = [constants.PLATFORM_READY]

    def __post_init__(self, *args: Any, **kwargs: Any) -> None:
        platform_fields = dataclass_fields(self)
        # get type field to analyze if mismatch type info is set.
        for platform_field in platform_fields:
            value = getattr(self, platform_field.name)
            if (
                value is not None
                and platform_field.name in self.supported_types
                and platform_field.name != self.type
            ):
                raise LisaException(
                    f"platform type '{self.type}' and extension "
                    f"'{platform_field.name}' mismatch"
                )


@dataclass_json(letter_case=LetterCase.CAMEL)
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
    # the schema is complex to convert, so need manual overwrite it.
    priority: Optional[Union[int, List[int]]] = field(default=None)
    # tag is a simple way to include test cases within same topic.
    tag: Optional[Union[str, List[str]]] = field(default=None)

    def __post_init__(self, *args: Any, **kwargs: Any) -> None:
        if isinstance(self.priority, int):
            if self.priority < 0 or self.priority > 3:
                raise LisaException(
                    f"priority range should be 0 to 3, but '{self.priority}'"
                )
        elif isinstance(self.priority, list):
            for priority in self.priority:
                if priority < 0 or priority > 3:
                    raise LisaException(
                        f"priority range should be 0 to 3, but '{priority}'"
                    )
        elif self.priority is not None:
            raise LisaException(
                f"priority must be integer, but '{self.priority}' "
                f"is '{type(self.priority)}'"
            )

        if isinstance(self.tag, list):
            for tag in self.tag:
                assert isinstance(
                    tag, str
                ), f"tag must be str, but '{tag}' is '{type(tag)}'"
        elif not isinstance(self.tag, str):
            if self.tag is not None:
                raise LisaException(
                    f"tag must be str, but '{self.tag}' is '{type(self.tag)}'"
                )


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class TestCase:
    """
    rules apply ordered on previous selection.
    The order of test cases running is not guaranteed, until it set dependencies.
    """

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
    # if it's false, the test cases are disable in current run.
    # it uses to control test cases dynamic form command line.
    enable: bool = field(default=True)
    # run this group of test cases several times
    # default is 1
    times: int = field(default=1, metadata=metadata(validate=validate.Range(min=1)))
    # retry times if fails. Default is 0, not to retry.
    retry: int = field(default=0, metadata=metadata(validate=validate.Range(min=0)))
    # each case with this rule will be run in a new environment.
    use_new_environment: bool = False
    # Once it's set, failed test result will be rewrite to success
    # it uses to work around some cases temporarily, don't overuse it.
    # default is false
    ignore_failure: bool = False
    # case should run on a specified environment
    environment: str = ""


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class Config:
    # run name prefix to help grouping results and put it in title.
    name: str = "not_named"
    parent: Optional[List[Parent]] = field(default=None)
    extension: Optional[Extension] = field(default=None)
    variable: Optional[List[Variable]] = field(default=None)
    artifact: Optional[List[Artifact]] = field(default=None)
    environment: Optional[EnvironmentRoot] = field(default=None)
    notifier: Optional[List[Notifier]] = field(default=None)
    platform: List[Platform] = field(default_factory=list)
    testcase: List[TestCase] = field(default_factory=list)

    def __post_init__(self, *args: Any, **kwargs: Any) -> None:
        if not self.platform:
            self.platform = [Platform(constants.PLATFORM_READY)]

        if not self.testcase:
            self.testcase = [TestCase("test", Criteria(area="demo"))]
