# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from unittest import TestCase
from unittest.mock import Mock

from assertpy import assert_that

from lisa.util import LisaException
from lisa.util.process import Process


class ProcessTestCase(TestCase):
    def test_wait_result_caching_prevents_reprocessing(self) -> None:
        from unittest.mock import MagicMock, patch

        shell = Mock()
        shell.is_posix = True
        shell.is_remote = False

        process = Process("test", shell)
        process._cmd = ["echo", "test"]
        process._timer = Mock()
        process._stdout_writer = Mock()
        process._stderr_writer = Mock()
        process.log_buffer = MagicMock()

        with (
            patch.object(process, "_process") as mock_process,
            patch.object(process, "is_running", side_effect=[True, False]),
            patch.object(process, "_recycle_resource"),
        ):
            process._timer.elapsed.return_value = 1.0
            mock_process.wait_for_result.return_value = Mock(
                output="test output",
                stderr_output="",
                return_code=0,
            )

            result1 = process.wait_result(timeout=10)
            result2 = process.wait_result(timeout=10)

            assert_that(result1).is_same_as(result2)
            assert_that(mock_process.wait_for_result.call_count).is_equal_to(1)

    def test_wait_result_timeout_with_raise_on_timeout_true(self) -> None:
        from unittest.mock import MagicMock, patch

        shell = Mock()
        shell.is_posix = True
        shell.is_remote = False

        process = Process("test", shell)
        process._cmd = ["sleep", "1"]
        process._stdout_writer = Mock()
        process._stderr_writer = Mock()
        process.log_buffer = MagicMock()

        # Mock both the local timer and the instance timer
        mock_timer = Mock()
        mock_timer.elapsed.side_effect = [5.0, 11.0, 11.0]
        process._timer = mock_timer

        with (
            patch.object(process, "_process"),
            patch.object(process, "is_running", side_effect=[True, False]),
            patch.object(process, "kill"),
            patch.object(process, "_recycle_resource"),
            patch("lisa.util.process.time.sleep"),  # Patch at import location
            patch("lisa.util.process.create_timer", return_value=mock_timer),
        ):
            process.log_buffer.getvalue.return_value = "partial output"

            with self.assertRaises(LisaException) as context:
                process.wait_result(timeout=10, raise_on_timeout=True)

            assert_that(str(context.exception)).contains("timeout after 10 seconds")

    def test_wait_result_timeout_with_raise_on_timeout_false(self) -> None:
        from unittest.mock import MagicMock, patch

        shell = Mock()
        shell.is_posix = True
        shell.is_remote = False

        process = Process("test", shell)
        process._cmd = ["sleep", "1"]
        process._stdout_writer = Mock()
        process._stderr_writer = Mock()
        process.log_buffer = MagicMock()

        # Mock both the local timer and the instance timer
        mock_timer = Mock()
        mock_timer.elapsed.side_effect = [5.0, 11.0, 11.0, 11.0]
        process._timer = mock_timer

        with (
            patch.object(process, "_process"),
            patch.object(process, "is_running", side_effect=[True, False]),
            patch.object(process, "kill"),
            patch.object(process, "_recycle_resource"),
            patch("lisa.util.process.time.sleep"),  # Patch at import location
            patch("lisa.util.process.create_timer", return_value=mock_timer),
        ):
            process.log_buffer.getvalue.return_value = "partial output"

            result = process.wait_result(timeout=10, raise_on_timeout=False)

            assert_that(result.is_timeout).is_true()
            assert_that(result.stdout).is_equal_to("partial output")
            assert_that(result.exit_code).is_equal_to(1)
