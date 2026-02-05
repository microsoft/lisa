# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import logging
import unittest
from dataclasses import dataclass, field
from functools import partial
from typing import Any, List, Optional, TypeVar

from lisa.search_space import (
    CountSpace,
    IntRange,
    RequirementMixin,
    ResultReason,
    SetSpace,
    check,
    check_countspace,
    generate_min_capability,
    generate_min_capability_countspace,
)
from lisa.util import LisaException
from lisa.util.logger import get_logger

T = TypeVar("T")


@dataclass
class MockSchema:
    number: Optional[int] = None


@dataclass
class MockItem(RequirementMixin):
    number: CountSpace = field(default_factory=partial(IntRange, min=1, max=5))

    def check(self, capability: Any) -> ResultReason:
        assert isinstance(capability, MockItem), f"actual: {type(capability)}"
        return check_countspace(self.number, capability.number)

    def _generate_min_capability(self, capability: Any) -> MockSchema:
        result = MockSchema()
        assert isinstance(capability, MockItem), f"actual: {type(capability)}"
        result.number = generate_min_capability_countspace(
            self.number, capability.number
        )

        return result


class SearchSpaceTestCase(unittest.TestCase):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._log = get_logger(f"{'.'.join(self.id().split('.')[-2:])}")

    def test_supported_intrange(self) -> None:
        self._verify_matrix(
            expected_meet=[
                [True, True, True, False, True, True, False, True, False, False],
                [True, True, False, False, True, True, False, False, False, False],
            ],
            expected_min=[
                [12, 10, 15, False, 10, 10, False, 15, False, False],
                [12, 10, False, False, 10, 10, False, False, False, False],
            ],
            requirements=[
                IntRange(min=10, max=15),
                IntRange(min=10, max=15, max_inclusive=False),
            ],
            capabilities=[
                IntRange(12),
                IntRange(10),
                IntRange(15),
                IntRange(20),
                IntRange(5, 11),
                IntRange(5, 10),
                IntRange(5, 10, max_inclusive=False),
                IntRange(15, 20),
                IntRange(1, 5),
                IntRange(20, 100),
            ],
        )

    def test_supported_countspace(self) -> None:
        expected_meet = [
            [True, True, True, True, True, True, True, True, True, True, True],
            [False, True, False, False, False, True, True, True, False, False, False],
            [False, False, True, False, False, True, False, True, True, False, False],
            [False, False, False, False, True, False, False, True, True, True, True],
            [False, True, True, False, False, True, True, True, True, False, False],
            [False, True, False, False, False, True, True, True, True, False, False],
            [False, True, True, False, True, True, True, True, True, True, True],
        ]
        expected_min: List[List[Any]] = [
            [None, 10, 15, 18, 25, 10, 10, 10, 12, 21, 21],
            [False, 10, False, False, False, 10, 10, 10, False, False, False],
            [False, False, 15, False, False, 15, False, 15, 15, False, False],
            [False, False, False, False, 25, False, False, 25, 25, 25, 25],
            [False, 10, 15, False, False, 10, 10, 10, 12, False, False],
            [False, 10, False, False, False, 10, 10, 10, 12, False, False],
            [False, 10, 15, False, 25, 10, 10, 10, 12, 21, 21],
        ]
        self._verify_matrix(
            expected_meet=expected_meet,
            expected_min=expected_min,
            requirements=[
                None,
                10,
                15,
                25,
                IntRange(min=10, max=15),
                IntRange(min=10, max=15, max_inclusive=False),
                [IntRange(min=10, max=15), IntRange(min=20, max=80)],
            ],
            capabilities=[
                None,
                10,
                15,
                18,
                25,
                IntRange(min=10, max=15),
                IntRange(min=10, max=15, max_inclusive=False),
                [IntRange(min=10, max=15), IntRange(min=20, max=80)],
                [IntRange(min=12, max=30)],
                [IntRange(min=21, max=25)],
                IntRange(min=21, max=25),
            ],
        )

    def test_supported_set_space(self) -> None:
        set_aa = set(["aa"])
        set_aa_bb = set(["aa", "bb"])
        set_aa_bb_cc = set(["aa", "bb", "cc"])
        set_aa_cc = set(["aa", "cc"])
        set_cc = set(["cc"])
        self._verify_matrix(
            expected_meet=[
                [True, True, True, True, True],
                [True, True, True, True, True],
                [False, False, False, True, False],
                [True, False, True, False, False],
                [True, False, True, False, False],
            ],
            expected_min=[
                [None, None, None, None, None],
                [None, None, None, None, None],
                [False, False, False, set_aa_bb, False],
                [None, False, None, False, False],
                [None, False, None, False, False],
            ],
            requirements=[
                SetSpace[str](is_allow_set=True),
                SetSpace[str](is_allow_set=False),
                SetSpace[str](items=set_aa_bb, is_allow_set=True),
                SetSpace[str](items=set_aa_bb),
                SetSpace[str](items=set_aa_bb, is_allow_set=False),
            ],
            capabilities=[
                SetSpace[str](is_allow_set=True),
                SetSpace[str](items=set_aa, is_allow_set=True),
                SetSpace[str](items=set_cc, is_allow_set=True),
                SetSpace[str](items=set_aa_bb_cc, is_allow_set=True),
                SetSpace[str](items=set_aa_cc, is_allow_set=True),
            ],
        )

    def test_generate_min_capability_not_supported(self) -> None:
        requirement = IntRange(min=5)
        capability = IntRange(max=4)

        with self.assertRaises(expected_exception=LisaException) as cm:
            requirement.generate_min_capability(capability)
        self.assertIn("doesn't support", str(cm.exception))

    def test_int_range_validation(self) -> None:
        with self.assertRaises(expected_exception=LisaException) as cm:
            IntRange(min=6, max=4)
        self.assertIn("shouldn't be greater than", str(cm.exception))

        # no exception
        IntRange(min=5, max=5)

        with self.assertRaises(expected_exception=LisaException) as cm:
            IntRange(min=5, max=5, max_inclusive=False)
        self.assertIn("shouldn't be equal to", str(cm.exception))

    def _verify_matrix(
        self,
        expected_meet: List[List[bool]],
        expected_min: List[List[Any]],
        requirements: List[T],
        capabilities: List[T],
    ) -> None:
        for r_index, requirement in enumerate(requirements):
            for c_index, capability in enumerate(capabilities):
                extra_msg = (
                    f"index: [{r_index},{c_index}], "
                    f"requirement: {requirement}, capability: {capability}"
                )
                if isinstance(requirement, RequirementMixin):
                    self._assert_check(
                        expected_meet[r_index][c_index],
                        requirement.check(capability),
                        extra_msg=extra_msg,
                    )

                    if expected_meet[r_index][c_index]:
                        actual_min = requirement.generate_min_capability(capability)
                        if expected_min[r_index][c_index] != actual_min:
                            self._log.info(extra_msg)
                            self._log.info(
                                f"expected_min: {expected_min[r_index][c_index]}"
                            )
                            self._log.info(f"actual_min: {actual_min}")
                        self.assertEqual(
                            expected_min[r_index][c_index], actual_min, extra_msg
                        )
                elif (
                    isinstance(requirement, IntRange)
                    or isinstance(requirement, int)
                    or isinstance(capability, IntRange)
                    or isinstance(capability, int)
                ):
                    self._assert_check(
                        expected_meet[r_index][c_index],
                        check_countspace(requirement, capability),  # type:ignore
                        extra_msg=extra_msg,
                    )
                    if expected_meet[r_index][c_index]:
                        actual_min = generate_min_capability_countspace(
                            requirement, capability  # type:ignore
                        )
                        if expected_min[r_index][c_index] != actual_min:
                            self._log.info(extra_msg)
                        self.assertEqual(
                            expected_min[r_index][c_index], actual_min, extra_msg
                        )
                else:
                    self._assert_check(
                        expected_meet[r_index][c_index],
                        check(requirement, capability),  # type:ignore
                        extra_msg=extra_msg,
                    )

                    if expected_meet[r_index][c_index]:
                        actual_min = generate_min_capability(
                            requirement, capability  # type:ignore
                        )
                        self.assertEqual(
                            expected_min[r_index][c_index], actual_min, extra_msg
                        )

    def _assert_check(
        self,
        expected_meet: bool,
        result: ResultReason,
        extra_msg: str = "",
    ) -> None:
        msg = f"expected result: {expected_meet}, actual: {result.result}"
        if extra_msg:
            msg = f"{msg}, {extra_msg}"

        show_all = self._outcome.result.showAll  # type: ignore
        if show_all or expected_meet != result.result:
            self._log.lines(logging.INFO, result.reasons)
        self.assertEqual(expected_meet, result.result, msg)
