import sys
from abc import abstractmethod
from dataclasses import dataclass, field
from typing import Any, Iterable, List, Optional, Set, TypeVar, Union

from dataclasses_json import LetterCase, dataclass_json  # type: ignore

from lisa.util import LisaException

T = TypeVar("T")


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
        if name:
            self.reasons.append(f"{self._prefix}/{name}: {reason}")
        else:
            self.reasons.append(f"{self._prefix}: {reason}")

    def merge(self, sub_result: Any, name: str = "") -> None:
        assert isinstance(sub_result, ResultReason), f"actual: {type(sub_result)}"
        self.result = self.result and sub_result.result
        for reason in sub_result.reasons:
            if name:
                self.reasons.append(f"{self._prefix}/{name}{reason}")
            else:
                self.reasons.append(f"{self._prefix}{reason}")


class RequirementMixin:
    @abstractmethod
    def check(self, capability: Any) -> ResultReason:
        raise NotImplementedError()

    @abstractmethod
    def _generate_min_capaiblity(self, capability: Any) -> Any:
        raise NotImplementedError()

    def generate_min_capaiblity(self, capability: Any) -> Any:
        check_result = self.check(capability)
        if not check_result.result:
            raise LisaException(
                "cannot get min value, capability doesn't support requirement"
            )
        return self._generate_min_capaiblity(capability)


T_SEARCH_SPACE = TypeVar("T_SEARCH_SPACE", bound=RequirementMixin)


@dataclass_json(letter_case=LetterCase.CAMEL)
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
        return f"[{self.min}-{self.max}],inc:{self.max_inclusive}"

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
                        f"capability ({capability}) is "
                        f"smaller than requirement min({self.min})"
                    )
                elif capability > self.max:
                    result.add_reason(
                        f"capability ({capability}) is "
                        f"bigger than requirement max({self.max})"
                    )
                elif capability == self.max and not self.max_inclusive:
                    result.add_reason(
                        f"capability ({capability}) equals "
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

    def _generate_min_capaiblity(self, capability: Any) -> int:
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
                    temp_min = self.generate_min_capaiblity(cap_item)
                    result = min(temp_min, result)

        return result


CountSpace = Union[int, List[IntRange], IntRange, None]


def _one_of_matched(
    requirement: Any, capabilities: List[T_SEARCH_SPACE]
) -> ResultReason:
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


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class SetSpace(RequirementMixin, Set[T]):
    is_allow_set: bool = False

    def __init__(
        self, is_allow_set: Optional[bool] = None, items: Optional[Iterable[T]] = None,
    ) -> None:
        if items:
            self.update(items)
        if is_allow_set is not None:
            self.is_allow_set = is_allow_set

    def check(self, capability: Any) -> ResultReason:
        result = ResultReason()
        if self.is_allow_set and len(self) > 0 and not capability:
            result.add_reason(
                "if requirements is allow set and len > 0, capability shouldn't be None"
            )

        assert isinstance(capability, SetSpace), f"actual: {type(capability)}"
        assert capability.is_allow_set, "capatility must be allow set"
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
                if len(self.intersection(capability)) > 0:
                    result.add_reason(
                        "requirements is exclusive, but capability include "
                        f"some options, requirements: '{self}', "
                        f"capability: '{capability}'"
                    )
        return result

    def _generate_min_capaiblity(self, capability: Any) -> Optional[Set[T]]:
        result = None
        if self.is_allow_set and len(self) > 0:
            result = self

        return result


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


def generate_min_capaiblity_countspace(
    requirement: CountSpace, capability: CountSpace
) -> int:
    check_result = check_countspace(requirement, capability)
    if not check_result.result:
        raise LisaException(
            "cannot get min value, capability doesn't support requirement"
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
        result = requirement.generate_min_capaiblity(capability)
    else:
        assert isinstance(requirement, list), f"actual: {type(requirement)}"
        result = sys.maxsize
        for req_item in requirement:
            temp_result = req_item.check(capability)
            if temp_result.result:
                temp_min = req_item.generate_min_capaiblity(capability)
                result = min(result, temp_min)

    return result


def check(
    requirement: Union[T_SEARCH_SPACE, List[T_SEARCH_SPACE], None],
    capability: Union[T_SEARCH_SPACE, List[T_SEARCH_SPACE], None],
) -> ResultReason:
    result = ResultReason()
    if requirement is not None:
        if capability is None:
            result.add_reason("capability shouldn't be None")
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


def generate_min_capaiblity(
    requirement: Union[T_SEARCH_SPACE, List[T_SEARCH_SPACE], None],
    capability: Union[T_SEARCH_SPACE, List[T_SEARCH_SPACE], None],
) -> Any:
    check_result = check(requirement, capability)
    if not check_result.result:
        raise LisaException(
            "cannot get min value, capability doesn't support requirement"
        )

    result: Optional[T_SEARCH_SPACE] = None
    if requirement is None:
        if capability is not None:
            requirement = capability
    if isinstance(requirement, list):
        result = None
        for req_item in requirement:
            temp_result = req_item.check(capability)
            if temp_result.result:
                temp_min = req_item.generate_min_capaiblity(capability)
                if result is None:
                    result = temp_min
                else:
                    # TODO: mutiple matches found, not supported well yet
                    # It can be improvied by impelment __eq__, __lt__ functions.
                    result = min(result, temp_min)
    elif requirement is not None:
        result = requirement.generate_min_capaiblity(capability)

    return result


def equal_list(first: Optional[List[Any]], second: Optional[List[Any]]) -> bool:
    if first is None or second is None:
        result = first is second
    else:
        result = len(first) == len(second)
        result = result and all(
            f_item == second[index] for index, f_item in enumerate(first)
        )
    return result
