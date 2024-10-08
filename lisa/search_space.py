# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import copy
import sys
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, List, Optional, Set, Type, TypeVar, Union

from dataclasses_json import dataclass_json

from lisa.util import LisaException, NotMeetRequirementException

T = TypeVar("T")


class RequirementMethod(Enum):
    generate_min_capability: str = "generate_min_capability"
    intersect: str = "intersect"


@dataclass
class ResultReason:
    result: bool = True
    reasons: List[str] = field(default_factory=list)
    _prefix: str = ""

    def append_prefix(self, prefix: str) -> None:
        if self._prefix or prefix:
            self._prefix = "/".join([self._prefix, prefix])

    def add_reason(self, reason: str, name: str = "") -> None:
        self.result = False

        if not any(reason in x for x in self.reasons):
            if ":" in reason:
                sep = "/"
            else:
                sep = ": "
            if name and self._prefix:
                reason = f"{self._prefix}/{name}{sep}{reason}"
            elif name:
                reason = f"{name}{sep}{reason}"
            elif self._prefix:
                reason = f"{self._prefix}{sep}{reason}"
            else:
                pass
            self.reasons.append(reason)

    def merge(self, sub_result: Any, name: str = "") -> None:
        assert isinstance(sub_result, ResultReason), f"actual: {type(sub_result)}"
        self.result = self.result and sub_result.result
        for reason in sub_result.reasons:
            self.add_reason(reason, name)


class RequirementMixin:
    def check(self, capability: Any) -> ResultReason:
        raise NotImplementedError()

    def generate_min_capability(self, capability: Any) -> Any:
        self._validate_result(capability)
        return self._generate_min_capability(capability)

    def intersect(self, capability: Any) -> Any:
        self._validate_result(capability)
        return self._intersect(capability)

    def _call_requirement_method(
        self, method: RequirementMethod, capability: Any
    ) -> Any:
        raise NotImplementedError(method)

    def _generate_min_capability(self, capability: Any) -> Any:
        return self._call_requirement_method(
            method=RequirementMethod.generate_min_capability,
            capability=capability,
        )

    def _intersect(self, capability: Any) -> Any:
        return self._call_requirement_method(
            method=RequirementMethod.intersect, capability=capability
        )

    def _validate_result(self, capability: Any) -> None:
        check_result = self.check(capability)
        if not check_result.result:
            raise NotMeetRequirementException(
                f"capability doesn't support requirement: {check_result.reasons}"
            )


T_SEARCH_SPACE = TypeVar("T_SEARCH_SPACE", bound=RequirementMixin)


@dataclass_json()
@dataclass
class IntRange(RequirementMixin):
    min: int = 0
    max: int = field(default=sys.maxsize)
    max_inclusive: bool = True

    def __post_init__(self, *args: Any, **kwargs: Any) -> None:
        if self.min > self.max:
            raise LisaException(
                f"min: {self.min} shouldn't be greater than max: {self.max}"
            )
        elif self.min == self.max and self.max_inclusive is False:
            raise LisaException(
                "min shouldn't be equal to max, if max_includes is False."
            )

    def __repr__(self) -> str:
        max_value = self.max if self.max < sys.maxsize else ""
        max_inclusive = ""
        if max_value:
            max_inclusive = "(inc)" if self.max_inclusive else "(exc)"
        return f"[{self.min},{max_value}{max_inclusive}]"

    def __eq__(self, __o: object) -> bool:
        assert isinstance(__o, IntRange), f"actual type: {type(__o)}"
        return (
            self.min == __o.min
            and self.max == __o.max
            and self.max_inclusive == __o.max_inclusive
        )

    def check(self, capability: Any) -> ResultReason:
        result = ResultReason()
        if capability is None:
            result.add_reason("capability shouldn't be None")
        else:
            if isinstance(capability, IntRange):
                if capability.max < self.min:
                    result.add_reason(
                        f"capability max({capability.max}) is "
                        f"smaller than requirement min({self.min})"
                    )
                elif capability.max == self.min and not capability.max_inclusive:
                    result.add_reason(
                        f"capability max({capability.max}) equals "
                        f"to requirement min({self.min}), but "
                        f"capability is not max_inclusive"
                    )
                elif capability.min > self.max:
                    result.add_reason(
                        f"capability min({capability.min}) is "
                        f"bigger than requirement max({self.max})"
                    )
                elif capability.min == self.max and not self.max_inclusive:
                    result.add_reason(
                        f"capability min({capability.min}) equals "
                        f"to requirement max({self.max}), but "
                        f"requirement is not max_inclusive"
                    )
            elif isinstance(capability, int):
                if capability < self.min:
                    result.add_reason(
                        f"capability({capability}) is "
                        f"smaller than requirement min({self.min})"
                    )
                elif capability > self.max:
                    result.add_reason(
                        f"capability ({capability}) is "
                        f"bigger than requirement max({self.max})"
                    )
                elif capability == self.max and not self.max_inclusive:
                    result.add_reason(
                        f"capability({capability}) equals "
                        f"to requirement max({self.max}), but "
                        f"requirement is not max_inclusive"
                    )
            else:
                assert isinstance(capability, list), f"actual: {type(capability)}"
                temp_result = _one_of_matched(self, capability)
                if not temp_result.result:
                    result.add_reason(
                        "no capability matches requirement, "
                        f"requirement: {self}, capability: {capability}"
                    )

        return result

    def _generate_min_capability(self, capability: Any) -> int:
        if isinstance(capability, int):
            result: int = capability
        elif isinstance(capability, IntRange):
            if self.min < capability.min:
                result = capability.min
            else:
                result = self.min
        else:
            assert isinstance(capability, list), f"actual: {type(capability)}"
            result = self.max if self.max_inclusive else self.max - 1
            for cap_item in capability:
                temp_result = self.check(cap_item)
                if temp_result.result:
                    temp_min = self.generate_min_capability(cap_item)
                    result = min(temp_min, result)

        return result

    def _intersect(self, capability: Any) -> Any:
        if isinstance(capability, int):
            return capability
        elif isinstance(capability, IntRange):
            result = IntRange(
                min=self.min, max=self.max, max_inclusive=self.max_inclusive
            )
            if self.min < capability.min:
                result.min = capability.min
            if self.max > capability.max:
                result.max = capability.max
                result.max_inclusive = capability.max_inclusive
            elif self.max == capability.max:
                result.max_inclusive = capability.max_inclusive and self.max_inclusive
        else:
            raise NotImplementedError(
                f"IntRange doesn't support other intersect on {type(capability)}."
            )
        return result


CountSpace = Union[int, List[IntRange], IntRange, None]


def decode_count_space(data: Any) -> Any:
    """
    CountSpace is complex to marshmallow, so it needs customized decode.
    Anyway, marshmallow can encode it correctly.
    """
    decoded_data: CountSpace = None
    if data is None or isinstance(data, int) or isinstance(data, IntRange):
        decoded_data = data
    elif isinstance(data, list):
        decoded_data = []
        for item in data:
            if isinstance(item, dict):
                decoded_data.append(IntRange.schema().load(item))  # type: ignore
            else:
                assert isinstance(item, IntRange), f"actual: {type(item)}"
                decoded_data.append(item)
    else:
        assert isinstance(data, dict), f"actual: {type(data)}"
        decoded_data = IntRange.schema().load(data)  # type: ignore
    return decoded_data


def _one_of_matched(requirement: Any, capabilities: List[Any]) -> ResultReason:
    result = ResultReason()
    supported = False
    assert isinstance(requirement, RequirementMixin), f"actual: {type(requirement)}"
    for cap_item in capabilities:
        temp_result = requirement.check(cap_item)
        if temp_result.result:
            supported = True
            break
    if not supported:
        result.add_reason("no one meeting requirement")

    return result


@dataclass_json()
@dataclass
class SetSpace(RequirementMixin, Set[T]):
    is_allow_set: bool = False
    items: List[T] = field(default_factory=list)

    def __init__(
        self,
        is_allow_set: Optional[bool] = None,
        items: Optional[Iterable[T]] = None,
    ) -> None:
        self.items: List[T] = []
        if items:
            self.update(items)
        if is_allow_set is not None:
            self.is_allow_set = is_allow_set

    def __repr__(self) -> str:
        return (
            f"allowed:{self.is_allow_set},"
            f"items:[{','.join([str(x) for x in self])}]"
        )

    def __post_init__(self, *args: Any, **kwargs: Any) -> None:
        self.update(self.items)

    def check(self, capability: Any) -> ResultReason:
        result = ResultReason()
        if self.is_allow_set and len(self) > 0 and not capability:
            result.add_reason(
                "if requirements is allow set and len > 0, capability shouldn't be None"
            )

        assert isinstance(capability, SetSpace), f"actual: {type(capability)}"
        assert capability.is_allow_set, "capability must be allow set"
        # if self.options is not None:
        # cap_set = capability.options
        if result.result:
            if self.is_allow_set:
                if not capability.issuperset(self):
                    result.add_reason(
                        "capability cannot support some of requirements, "
                        f"requirement: '{self}'"
                        f"capability: '{capability}', "
                    )
            else:
                inter_set: Set[Any] = self.intersection(capability)
                if len(inter_set) > 0:
                    names: List[str] = []
                    for item in inter_set:
                        if isinstance(item, type):
                            names.append(item.__name__)
                        elif isinstance(item, object):
                            names.append(item.__class__.__name__)
                        else:
                            names.append(item)
                    result.add_reason(f"requirements excludes {names}")
        return result

    def add(self, element: T) -> None:
        super().add(element)
        self.items.append(element)

    def remove(self, element: T) -> None:
        super().remove(element)
        self.items.remove(element)

    def isunique(self, element: T) -> bool:
        return len(self.items) == 1 and self.items[0] == element

    def update(self, *s: Iterable[T]) -> None:
        super().update(*s)
        self.items.extend(*s)

    def _generate_min_capability(self, capability: Any) -> Optional[Set[T]]:
        result: Optional[SetSpace[T]] = None
        if self.is_allow_set and len(self) > 0:
            assert isinstance(capability, SetSpace), f"actual: {type(capability)}"
            result = SetSpace(is_allow_set=self.is_allow_set)
            if len(capability) > 0:
                for item in self:
                    if item in capability:
                        result.add(item)

        return result

    def _intersect(self, capability: Any) -> Any:
        return self._generate_min_capability(capability)


def decode_set_space(data: Any) -> Any:
    """
    not sure what's reason, __post_init__ won't be called automatically.
    So write this decoder to force it's called on deserializing
    """
    result = None
    if data:
        result = SetSpace.schema().load(data)  # type: ignore
    return result


def decode_set_space_by_type(
    data: Any, base_type: Type[T]
) -> Optional[Union[SetSpace[T], T]]:
    if isinstance(data, dict):
        new_data = SetSpace[T](is_allow_set=True)
        types = data.get("items", [])
        for item in types:
            new_data.add(base_type(item))  # type: ignore
        decoded_data: Optional[Union[SetSpace[T], T]] = new_data
    elif isinstance(data, list):
        new_data = SetSpace[T](is_allow_set=True)
        for item in data:
            new_data.add(base_type(item))  # type: ignore
        decoded_data = new_data
    elif isinstance(data, (str, int)):
        decoded_data = base_type(data)  # type: ignore
    elif isinstance(data, SetSpace):
        decoded_data = data
    else:
        raise LisaException(f"unknown data type: {type(data)}")
    return decoded_data


def check_countspace(requirement: CountSpace, capability: CountSpace) -> ResultReason:
    result = ResultReason()
    if requirement is not None:
        if capability is None:
            result.add_reason(
                "if requirements isn't None, capability shouldn't be None"
            )
        else:
            if isinstance(requirement, int):
                if isinstance(capability, int):
                    if requirement != capability:
                        result.add_reason(
                            "requirement is a number, capability should be exact "
                            f"much, but requirement: {requirement}, "
                            f"capability: {capability}"
                        )
                elif isinstance(capability, IntRange):
                    temp_result = capability.check(requirement)
                    if not temp_result.result:
                        result.add_reason(
                            "requirement is a number, capability should include it, "
                            f"but requirement: {requirement}, capability: {capability}"
                        )
                else:
                    assert isinstance(capability, list), f"actual: {type(capability)}"
                    temp_requirement = IntRange(min=requirement, max=requirement)
                    temp_result = _one_of_matched(temp_requirement, capability)
                    if not temp_result.result:
                        result.add_reason(
                            f"requirement is a number, no capability matched, "
                            f"requirement: {requirement}, capability: {capability}"
                        )
            elif isinstance(requirement, IntRange):
                result.merge(requirement.check(capability))
            else:
                assert isinstance(requirement, list), f"actual: {type(requirement)}"

                supported = False
                for req_item in requirement:
                    temp_result = req_item.check(capability)
                    if temp_result.result:
                        supported = True
                if not supported:
                    result.add_reason(
                        "no capability matches requirement, "
                        f"requirement: {requirement}, capability: {capability}"
                    )
    return result


def generate_min_capability_countspace(
    requirement: CountSpace, capability: CountSpace
) -> int:
    check_result = check_countspace(requirement, capability)
    if not check_result.result:
        raise NotMeetRequirementException(
            "cannot get min value, capability doesn't support requirement: "
            f"{check_result.reasons}"
        )
    if requirement is None:
        if capability:
            requirement = capability
            result: int = sys.maxsize
        else:
            result = 0
    if isinstance(requirement, int):
        result = requirement
    elif isinstance(requirement, IntRange):
        result = requirement.generate_min_capability(capability)
    else:
        assert isinstance(requirement, list), f"actual: {type(requirement)}"
        result = sys.maxsize
        for req_item in requirement:
            temp_result = req_item.check(capability)
            if temp_result.result:
                temp_min = req_item.generate_min_capability(capability)
                result = min(result, temp_min)

    return result


def intersect_countspace(requirement: CountSpace, capability: CountSpace) -> Any:
    check_result = check_countspace(requirement, capability)
    if not check_result.result:
        raise NotMeetRequirementException(
            "cannot get intersect, capability doesn't support requirement: "
            f"{check_result.reasons}"
        )
    if requirement is None and capability:
        return copy.copy(capability)
    if isinstance(requirement, int):
        result = requirement
    elif isinstance(requirement, IntRange):
        result = requirement.intersect(capability)
    else:
        raise LisaException(
            f"not support to get intersect on countspace type: {type(requirement)}"
        )

    return result


def check_setspace(
    requirement: Optional[Union[SetSpace[T], T]],
    capability: Optional[Union[SetSpace[T], T]],
) -> ResultReason:
    result = ResultReason()
    if capability is None:
        result.add_reason("capability shouldn't be None")
    else:
        if requirement is not None:
            has_met_check = False
            if not isinstance(capability, SetSpace):
                capability = SetSpace[T](items=[capability])
            if not isinstance(requirement, SetSpace):
                requirement = SetSpace[T](items=[requirement])
            for item in requirement:
                if item in capability:
                    has_met_check = True
                    break
            if not has_met_check:
                result.add_reason(
                    f"requirement not supported in capability. "
                    f"requirement: {requirement}, "
                    f"capability: {capability}"
                )
    return result


def generate_min_capability_setspace_by_priority(
    requirement: Optional[Union[SetSpace[T], T]],
    capability: Optional[Union[SetSpace[T], T]],
    priority_list: List[T],
) -> T:
    check_result = check_setspace(requirement, capability)
    if not check_result.result:
        raise NotMeetRequirementException(
            "cannot get min value, capability doesn't support requirement"
            f"{check_result.reasons}"
        )

    assert capability is not None, "Capability shouldn't be None"

    # Ensure that both cap and req are instance of SetSpace
    if not isinstance(capability, SetSpace):
        capability = SetSpace[T](items=[capability])
    if requirement is None:
        requirement = capability
    if not isinstance(requirement, SetSpace):
        requirement = SetSpace[T](items=[requirement])

    # Find min capability
    min_cap: Optional[T] = None
    for item in priority_list:
        if item in requirement and item in capability:
            min_cap = item
            break
    assert min_cap is not None, (
        "Cannot find min capability, "
        f"requirement: '{requirement}', "
        f"capability: '{capability}'."
    )

    return min_cap


def intersect_setspace_by_priority(
    requirement: Optional[Union[SetSpace[T], T]],
    capability: Optional[Union[SetSpace[T], T]],
    priority_list: List[T],
) -> Any:
    # intersect doesn't need to take care about priority.
    check_result = check_setspace(requirement, capability)
    if not check_result.result:
        raise NotMeetRequirementException(
            f"capability doesn't support requirement: {check_result.reasons}"
        )

    assert capability is not None, "Capability shouldn't be None"

    value = SetSpace[T]()
    # Ensure that both cap and req are instance of SetSpace
    if not isinstance(capability, SetSpace):
        capability = SetSpace[T](items=[capability])
    if requirement is None:
        requirement = capability
    if not isinstance(requirement, SetSpace):
        requirement = SetSpace[T](items=[requirement])

    # Find min capability
    for item in requirement:
        if item in capability:
            value.add(item)

    return value


def count_space_to_int_range(count_space: CountSpace) -> IntRange:
    if count_space is None:
        result = IntRange(min=sys.maxsize * -1, max=sys.maxsize)
    elif isinstance(count_space, int):
        result = IntRange(min=count_space, max=count_space)
    elif isinstance(count_space, IntRange):
        result = count_space
    else:
        raise LisaException(
            f"unsupported type: {type(count_space)}, value: '{count_space}'"
        )

    return result


def check(
    requirement: Union[T_SEARCH_SPACE, List[T_SEARCH_SPACE], None],
    capability: Union[T_SEARCH_SPACE, List[T_SEARCH_SPACE], None],
) -> ResultReason:
    result = ResultReason()
    if requirement is not None:
        if capability is None:
            result.add_reason(
                f"capability shouldn't be None, requirement: [{requirement}]"
            )
        elif isinstance(requirement, (list)):
            supported = False
            for req_item in requirement:
                temp_result = req_item.check(capability)
                if temp_result.result:
                    supported = True
            if not supported:
                result.add_reason(
                    "no capability meet any of requirement, "
                    f"requirement: {requirement}, capability: {capability}"
                )
        else:
            result.merge(requirement.check(capability))
    return result


def _call_requirement_method(
    method: RequirementMethod,
    requirement: Union[T_SEARCH_SPACE, List[T_SEARCH_SPACE], None],
    capability: Union[T_SEARCH_SPACE, List[T_SEARCH_SPACE], None],
) -> Any:
    check_result = check(requirement, capability)
    if not check_result.result:
        raise NotMeetRequirementException(
            f"cannot call {method.value}, capability doesn't support requirement"
        )

    result: Optional[T_SEARCH_SPACE] = None
    if requirement is None:
        if capability is not None:
            requirement = capability
    if (
        isinstance(requirement, list)
        and method == RequirementMethod.generate_min_capability
    ):
        result = None
        for req_item in requirement:
            temp_result = req_item.check(capability)
            if temp_result.result:
                temp_min = getattr(req_item, method.value)(capability)
                if result is None:
                    result = temp_min
                else:
                    # TODO: multiple matches found, not supported well yet
                    # It can be improved by implement __eq__, __lt__ functions.
                    result = min(result, temp_min)
    elif requirement is not None:
        result = getattr(requirement, method.value)(capability)

    return result


def generate_min_capability(
    requirement: Union[T_SEARCH_SPACE, List[T_SEARCH_SPACE], None],
    capability: Union[T_SEARCH_SPACE, List[T_SEARCH_SPACE], None],
) -> Any:
    return _call_requirement_method(
        RequirementMethod.generate_min_capability,
        requirement=requirement,
        capability=capability,
    )


def intersect(
    requirement: Union[T_SEARCH_SPACE, List[T_SEARCH_SPACE], None],
    capability: Union[T_SEARCH_SPACE, List[T_SEARCH_SPACE], None],
) -> Any:
    return _call_requirement_method(
        RequirementMethod.intersect, requirement=requirement, capability=capability
    )


def equal_list(first: Optional[List[Any]], second: Optional[List[Any]]) -> bool:
    if first is None or second is None:
        result = first is second
    else:
        result = len(first) == len(second)
        result = result and all(
            f_item == second[index] for index, f_item in enumerate(first)
        )
    return result


def create_set_space(
    included_set: Optional[Iterable[T]],
    excluded_set: Optional[Iterable[T]],
    name: str = "",
) -> Optional[SetSpace[T]]:
    if included_set and excluded_set:
        raise LisaException(f"cannot set both included and excluded {name}")
    if included_set or excluded_set:
        set_space: Optional[SetSpace[T]] = SetSpace()
        assert set_space is not None
        if included_set:
            set_space.is_allow_set = True
            set_space.update(included_set)
        else:
            assert excluded_set
            set_space.is_allow_set = False
            set_space.update(excluded_set)
    else:
        set_space = None
    return set_space


def decode_nullable_set_space(
    data: Any, base_type: Any, default_values: Any, is_allow_set: bool = False
) -> Any:
    if str(data).strip():
        return decode_set_space_by_type(data, base_type=base_type)
    else:
        return decode_set_space_by_type(
            SetSpace(is_allow_set=is_allow_set, items=default_values),
            base_type=base_type,
        )
