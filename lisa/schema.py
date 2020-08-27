from dataclasses import dataclass, field
from dataclasses import fields as dataclass_fields
from typing import Any, Callable, ClassVar, List, Optional, Type, TypeVar, Union

from dataclasses_json import (  # type: ignore
    DataClassJsonMixin,
    LetterCase,
    config,
    dataclass_json,
)
from marshmallow import ValidationError, fields, validate

from lisa.util import LisaException, constants

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
    encoder = kwargs.pop("encoder", None)
    decoder = kwargs.pop("decoder", None)
    # keep data_key for underlying marshmallow
    field_name = kwargs.get("data_key")
    return config(
        field_name=field_name,
        encoder=encoder,
        decoder=decoder,
        mm_field=field_function(*args, **kwargs),
    )


T = TypeVar("T", bound=DataClassJsonMixin)
U = TypeVar("U")


class ListableValidator(validate.Validator):
    default_message = ""

    def __init__(
        self,
        value_type: U,
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
                    validator(value)  # type: ignore
        elif isinstance(value, list):
            for value_item in value:
                assert isinstance(value_item, self._value_type), (
                    f"must be '{self._value_type}' but '{value_item}' "
                    f"is '{type(value_item)}'"
                )
                if self._inner_validator:
                    for validator in self._inner_validator:
                        validator(value_item)  # type: ignore
        elif value is not None:
            raise ValidationError(
                f"must be Union[{self._value_type}, List[{self._value_type}]], "
                f"but '{value}' is '{type(value)}'"
            )
        return value


class ExtendableSchemaMixin:
    def get_extended_runbook(
        self, runbook_type: Type[T], field_name: str = ""
    ) -> Optional[T]:
        """
        runbook_type: type of runbook
        field_name: the field name which stores the data, if it's "", get it from type
        """
        assert issubclass(
            runbook_type, DataClassJsonMixin
        ), "runbook_type must annotate from DataClassJsonMixin"
        if not field_name:
            assert hasattr(self, constants.TYPE), (
                f"cannot find type attr on '{runbook_type.__name__}'."
                f"either set field_name or make sure type attr exists."
            )
            field_name = getattr(self, constants.TYPE)
        assert hasattr(self, field_name), f"cannot find attr '{field_name}'"

        customized_runbook = getattr(self, field_name)
        if customized_runbook is not None and not isinstance(
            customized_runbook, runbook_type
        ):
            raise LisaException(
                f"extended type mismatch, expected type: {runbook_type} "
                f"data type: {type(customized_runbook)}"
            )
        return customized_runbook


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
    share runbook for similar runs.
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
    # it's not recommended highly to put secret in runbook directly.
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
class IntegerRange:
    min: int
    max: int


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
    core_count: int = field(
        default=1,
        metadata=metadata(data_key="coreCount", validate=validate.Range(min=1)),
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
                node_type = node_raw[constants.TYPE]
                if node_type == constants.ENVIRONMENTS_NODES_LOCAL:
                    node: Union[
                        NodeSpec, LocalNode, RemoteNode
                    ] = LocalNode.schema().load(  # type:ignore
                        node_raw
                    )
                elif node_type == constants.ENVIRONMENTS_NODES_REMOTE:
                    node = RemoteNode.schema().load(node_raw)  # type:ignore
                elif node_type == constants.ENVIRONMENTS_NODES_SPEC:
                    node = NodeSpec.schema().load(node_raw)  # type:ignore
                else:
                    raise LisaException(f"unknown node type '{node_type}': {node_raw}")
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

    admin_username: str = "lisa"
    admin_password: str = ""
    admin_private_key_file: str = ""

    # True means not to delete an environment, even it's created by lisa
    reserve_environment: bool = False

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

        if self.type != constants.PLATFORM_READY:
            if self.admin_password and self.admin_private_key_file:
                raise LisaException(
                    "only one of admin_password and admin_private_key_file can be set"
                )
            elif not self.admin_password and not self.admin_private_key_file:
                raise LisaException(
                    "one of admin_password and admin_private_key_file must be set"
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
    # the runbook is complex to convert, so manual overwrite it in __post_init__.
    priority: Optional[Union[int, List[int]]] = field(
        default=None,
        metadata=metadata(
            validate=ListableValidator(int, validate.Range(min=0, max=3))
        ),
    )
    # tag is a simple way to include test cases within same topic.
    tag: Optional[Union[str, List[str]]] = field(
        default=None, metadata=metadata(validate=ListableValidator(str))
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
class Runbook:
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
