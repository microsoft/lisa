from functools import partial
from typing import Any, Iterable, List
from unittest import TestCase
from unittest.mock import Mock

from assertpy import assert_that

from lisa.util import TestPanicException, check_test_panic, get_first_combination, to_bool


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

    def test_to_bool_positive(self):
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
            # Ints are converted to bools.
            # 0 is false, everything else is true.
            (-1, True),
            (0, False),
            (1, True),
            (2, True),
        ]

        for input_str, expected in test_cases:
            result = to_bool(input_str)
            assert_that(result).described_as(
                f"Failed for input: {input_str}"
            ).is_equal_to(expected)

    def test_to_bool_negative(self):
        test_cases = [
            ("invalid", ValueError),
            ("10", ValueError),
            ("2", ValueError),
            ("yesyes", ValueError),
            ("no no", ValueError),
            ("yes no", ValueError),
            ("no yes", ValueError),
            ("one", ValueError),
            (None, TypeError),
            (1.5, TypeError),
            (object(), TypeError),
            ([], TypeError),
            ({}, TypeError),
        ]
        for input_value, expected_exception in test_cases:
            with self.assertRaises(expected_exception):
                to_bool(input_value)

    def _check(self, values: List[Any]) -> Any:
        print(f"checked results: {values}")
        return sum(values) == self._expected

    def _next(self, item: Any) -> Iterable[Any]:
        values = item[1]
        for value in values:
            print(f"item: {item[0]}, returned: {value}")
            yield value


class TestPanicTestCase(TestCase):
    """Test cases for test panic detection functionality"""

    def test_test_panic_exception_creation(self):
        """Test TestPanicException class creation and string representation"""
        panics = ["panicked at 'assertion failed'", "stack backtrace:"]
        exception = TestPanicException("test_stage", panics, "test_log.txt")

        assert_that(exception.stage).is_equal_to("test_stage")
        assert_that(exception.panics).is_equal_to(panics)
        assert_that(exception.source).is_equal_to("test_log.txt")

        exception_str = str(exception)
        assert_that(exception_str).contains("test_stage")
        assert_that(exception_str).contains("test_log.txt")
        assert_that(exception_str).contains("panicked at 'assertion failed'")

    def test_check_test_panic_with_both_patterns(self):
        """Test check_test_panic when both 'panicked at' and 'stack backtrace' are present"""
        content = """
        Running test...
        thread 'main' panicked at 'assertion failed: x == y', tests/test.rs:42:5
        stack backtrace:
           0: rust_begin_unwind
           1: core::panicking::panic_fmt
        Test failed
        """
        log = Mock()

        with self.assertRaises(TestPanicException) as context:
            check_test_panic(content, "test_stage", log, test_result=None)

        exception = context.exception
        assert_that(exception.stage).is_equal_to("test_stage")
        assert_that(exception.panics).is_not_empty()
        # Should find both patterns
        panic_str = " ".join(exception.panics)
        assert_that(panic_str.lower()).contains("panicked at")
        assert_that(panic_str.lower()).contains("stack backtrace")

    def test_check_test_panic_with_only_panicked_at(self):
        """Test check_test_panic when only 'panicked at' pattern is present"""
        content = """
        Running test...
        thread 'main' panicked at 'assertion failed: x == y', tests/test.rs:42:5
        Test failed
        """
        log = Mock()

        with self.assertRaises(TestPanicException) as context:
            check_test_panic(content, "test_stage", log, test_result=None)

        exception = context.exception
        assert_that(exception.panics).is_not_empty()
        panic_str = " ".join(exception.panics)
        assert_that(panic_str.lower()).contains("panicked at")

    def test_check_test_panic_with_only_stack_backtrace(self):
        """Test check_test_panic when only 'stack backtrace' pattern is present"""
        content = """
        Running test...
        Error occurred
        stack backtrace:
           0: rust_begin_unwind
           1: core::panicking::panic_fmt
        Test failed
        """
        log = Mock()

        with self.assertRaises(TestPanicException) as context:
            check_test_panic(content, "test_stage", log, test_result=None)

        exception = context.exception
        assert_that(exception.panics).is_not_empty()
        panic_str = " ".join(exception.panics)
        assert_that(panic_str.lower()).contains("stack backtrace")

    def test_check_test_panic_no_panic(self):
        """Test check_test_panic when no panic patterns are present"""
        content = """
        Running test...
        All tests passed successfully
        Test completed
        """
        log = Mock()

        # Should not raise any exception
        check_test_panic(content, "test_stage", log, test_result=None)

    def test_check_test_panic_with_test_result_empty_message(self):
        """Test check_test_panic appends to test_result with empty message"""
        content = """
        thread 'main' panicked at 'assertion failed', test.rs:10:5
        stack backtrace:
           0: rust_begin_unwind
        """
        log = Mock()
        test_result = Mock()
        test_result.message = ""

        check_test_panic(
            content, "test_stage", log, test_result=test_result, node_name="test_node"
        )

        # Should set the message instead of raising exception
        assert_that(test_result.message).is_not_empty()
        assert_that(test_result.message).contains("TEST PANIC DETECTED")
        assert_that(test_result.message).contains("test_node")
        assert_that(test_result.message).contains("panicked at")

    def test_check_test_panic_with_test_result_existing_message(self):
        """Test check_test_panic appends to test_result with existing message"""
        content = """
        thread 'main' panicked at 'assertion failed', test.rs:10:5
        stack backtrace:
           0: rust_begin_unwind
        """
        log = Mock()
        test_result = Mock()
        test_result.message = "Original failure message"

        check_test_panic(
            content, "test_stage", log, test_result=test_result, node_name="test_node"
        )

        # Should append to existing message
        assert_that(test_result.message).contains("Original failure message")
        assert_that(test_result.message).contains("TEST PANIC DETECTED")
        assert_that(test_result.message).contains("test_node")
        assert_that(test_result.message).contains("panicked at")

    def test_check_test_panic_with_test_result_no_panic(self):
        """Test check_test_panic with test_result when no panic is detected"""
        content = """
        Running test...
        All tests passed
        """
        log = Mock()
        test_result = Mock()
        test_result.message = "Test passed"

        check_test_panic(
            content, "test_stage", log, test_result=test_result, node_name="test_node"
        )

        # Message should remain unchanged
        assert_that(test_result.message).is_equal_to("Test passed")

    def test_check_test_panic_custom_source(self):
        """Test check_test_panic with custom source parameter"""
        content = """
        panicked at 'error', file.rs:1:1
        """
        log = Mock()

        with self.assertRaises(TestPanicException) as context:
            check_test_panic(
                content, "test_stage", log, test_result=None, source="custom_log.txt"
            )

        exception = context.exception
        assert_that(exception.source).is_equal_to("custom_log.txt")

    def test_check_test_panic_case_insensitive_stack_backtrace(self):
        """Test that stack backtrace pattern is case insensitive"""
        content = """
        panicked at 'error', file.rs:1:1
        STACK BACKTRACE:
           0: rust_begin_unwind
        """
        log = Mock()

        with self.assertRaises(TestPanicException) as context:
            check_test_panic(content, "test_stage", log, test_result=None)

        exception = context.exception
        assert_that(exception.panics).is_not_empty()
        panic_str = " ".join(exception.panics).lower()
        assert_that(panic_str).contains("stack backtrace")

    def test_check_test_panic_multiline_panic_message(self):
        """Test check_test_panic with multiline panic messages"""
        content = """
        Running Cloud Hypervisor test...
        thread 'test_boot' panicked at 'Failed to boot VM: timeout waiting for response', ch-remote/src/main.rs:145:13
        note: run with `RUST_BACKTRACE=1` environment variable to display a backtrace
        stack backtrace:
           0: rust_begin_unwind
                 at /rustc/library/std/src/panicking.rs:584:5
           1: core::panicking::panic_fmt
                 at /rustc/library/core/src/panicking.rs:142:14
        Error: test failed
        """
        log = Mock()

        with self.assertRaises(TestPanicException) as context:
            check_test_panic(content, "integration_test", log, test_result=None)

        exception = context.exception
        assert_that(exception.panics).is_not_empty()
        assert_that(len(exception.panics)).is_greater_than(1)
