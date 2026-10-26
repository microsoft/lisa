# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from unittest import TestCase
from unittest.mock import MagicMock, Mock, call, patch

from semver import VersionInfo

from lisa.operating_system import CBLMariner
from lisa.tools import Gcc, Git, Make
from lisa.tools.iperf3 import Iperf3
from lisa.util.process import Process


class Iperf3TestCase(TestCase):
    def test_client_wait_includes_completion_tolerance(self) -> None:
        for run_time_seconds in (10, 1800):
            with self.subTest(run_time_seconds=run_time_seconds):
                iperf3 = Iperf3.__new__(Iperf3)
                process = Mock(spec=Process)

                with patch.object(iperf3, "run_as_client_async", return_value=process):
                    result = iperf3.run_as_client(
                        "10.0.0.5", run_time_seconds=run_time_seconds
                    )

                self.assertIs(result, process.wait_result.return_value)
                process.wait_result.assert_called_once_with(
                    expected_exit_code=0,
                    expected_exit_code_failure_message="fail to launch iperf3 client",
                    timeout=run_time_seconds + 60,
                )

    def test_client_completion_overhead_is_bounded(self) -> None:
        for completion_time in (1805.0, 1860.0, 1861.0):
            with self.subTest(completion_time=completion_time):
                iperf3 = Iperf3.__new__(Iperf3)
                shell = Mock(is_posix=True, is_remote=False)
                process = Process("iperf-client", shell)
                process._cmd = ["iperf3", "-t", "1800", "-c", "10.0.0.5"]
                process._stdout_writer = Mock()
                process._stderr_writer = Mock()
                process.log_buffer = MagicMock()
                timer = Mock()
                timer.elapsed.return_value = completion_time
                process._timer = timer

                with (
                    patch.object(iperf3, "run_as_client_async", return_value=process),
                    patch.object(process, "_process") as backend,
                    patch.object(process, "is_running", side_effect=[True, False]),
                    patch.object(process, "kill") as kill,
                    patch.object(process, "_recycle_resource"),
                    patch("lisa.util.process.time.sleep"),
                    patch("lisa.util.process.create_timer", return_value=timer),
                ):
                    backend.wait_for_result.return_value = Mock(
                        output="transfer completed", stderr_output="", return_code=0
                    )

                    if completion_time > 1860:
                        with self.assertRaisesRegex(
                            AssertionError, "fail to launch iperf3 client"
                        ):
                            iperf3.run_as_client("10.0.0.5", run_time_seconds=1800)
                        kill.assert_called_once()
                        backend.wait_for_result.assert_not_called()
                    else:
                        result = iperf3.run_as_client("10.0.0.5", run_time_seconds=1800)
                        self.assertEqual(result.exit_code, 0)
                        self.assertEqual(result.stdout, "transfer completed")
                        kill.assert_not_called()
                        backend.wait_for_result.assert_called_once()

    def test_install_loads_source_build_dependencies(self) -> None:
        tools = MagicMock()
        iperf3 = Iperf3.__new__(Iperf3)
        iperf3.node = MagicMock(tools=tools)
        iperf3._log = MagicMock()

        parent = MagicMock()
        parent.attach_mock(tools.get, "get")

        with patch.object(iperf3, "_install", return_value=True) as install:
            parent.attach_mock(install, "install")
            self.assertTrue(iperf3.install())

        parent.assert_has_calls(
            [call.get(Git), call.get(Make), call.get(Gcc), call.install()]
        )

    def test_source_build_installs_cbl_mariner_linker_dependencies(self) -> None:
        cbl_mariner = MagicMock(spec=CBLMariner)
        cbl_mariner.information.version = VersionInfo.parse("3.0.0")
        iperf3 = Iperf3.__new__(Iperf3)
        iperf3.node = MagicMock(os=cbl_mariner)

        iperf3._install_dep_packages()

        cbl_mariner.install_packages.assert_called_once_with(
            ["binutils", "glibc-devel", "build-essential"]
        )

    def test_source_build_installs_azure_linux_4_dependencies(self) -> None:
        azure_linux = MagicMock(spec=CBLMariner)
        azure_linux.information.version = VersionInfo.parse("4.0.0")
        iperf3 = Iperf3.__new__(Iperf3)
        iperf3.node = MagicMock(os=azure_linux)

        iperf3._install_dep_packages()

        azure_linux.install_packages.assert_called_once_with(
            ["binutils", "glibc-devel", "gcc", "make"]
        )
