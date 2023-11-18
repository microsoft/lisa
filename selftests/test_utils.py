from functools import partial
from typing import Any, Iterable, List
from unittest import TestCase

from assertpy import assert_that

from lisa.util import get_first_combination


class UtilsTestCase(TestCase):
    _caps: List[Any] = [
        ("a", [1, 2, 3, 4]),
        ("b", [1, 2, 3, 4]),
        ("c", [1, 2, 3, 4]),
    ]
    _expected = 4

    def test_first_combination_matched(self):
        results = []

        self._expected = 4
        found = get_first_combination(
            items=self._caps,
            index=0,
            results=results,
            check=partial(self._check),
            next_value=self._next,
            can_early_stop=False,
        )

        assert_that(found).described_as("cannot found matched item").is_equal_to(True)
        assert_that(results).described_as("unexpected results").is_equal_to([1, 1, 2])

    def test_first_combination_not_matched(self):
        results = []

        self._expected = 13
        found = get_first_combination(
            items=self._caps,
            index=0,
            results=results,
            check=partial(self._check),
            next_value=self._next,
            can_early_stop=False,
        )

        assert_that(found).described_as("Shouldn't found matched item").is_equal_to(
            False
        )
        assert_that(results).described_as("unexpected results").is_equal_to([])

    def _check(self, values: List[Any]) -> Any:
        print(f"checked results: {values}")
        return sum(values) == self._expected

    def _next(self, item: Any) -> Iterable[Any]:
        values = item[1]
        for value in values:
            print(f"item: {item[0]}, returned: {value}")
            yield value
