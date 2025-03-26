from functools import partial
from typing import Any, Iterable, List
from unittest import TestCase

from assertpy import assert_that

from lisa.util import get_first_combination, str_to_bool


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

    def test_str_to_bool_positive(self):
        test_cases = [
            # Basic tests.
            ("True", True),
            ("False", False),
            ("yes", True),
            ("no", False),
            ("1", True),
            ("0", False),
            # Should also work with different casing and whitepace.
            # Rather than doing this exhaustively, we just test
            # some random cases.
            ("true", True),
            ("FALSE", False),
            (" 1", True),
            ("faLse", False),
            ("  yes  ", True),
            ("  false", False),
            ("faLsE ", False),
            # Bools are the identity function.
            (True, True),
            (False, False),
        ]

        for input_str, expected in test_cases:
            result = str_to_bool(input_str)
            assert_that(result).described_as(
                f"Failed for input: {input_str}"
            ).is_equal_to(expected)

    def test_str_to_bool_negative(self):
        test_cases = [
            "invalid",
            "10",
            "2",
            "yesyes",
            "no no",
            "yes no",
            "no yes",
            "one",
        ]

        for input_str in test_cases:
            try:
                str_to_bool(input_str)
                assert_that(False).described_as(
                    f"Input '{input_str}' should raise an error"
                ).is_true()
            except ValueError:
                continue

    def _check(self, values: List[Any]) -> Any:
        print(f"checked results: {values}")
        return sum(values) == self._expected

    def _next(self, item: Any) -> Iterable[Any]:
        values = item[1]
        for value in values:
            print(f"item: {item[0]}, returned: {value}")
            yield value
