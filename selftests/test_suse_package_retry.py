# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from unittest import TestCase
from unittest.mock import MagicMock, call, patch

from lisa.operating_system import Suse
from lisa.util import LisaException, MissingPackagesException
from lisa.util.process import ExecutableResult


class SusePackageRetryTestCase(TestCase):
    def setUp(self) -> None:
        self.node = MagicMock()
        self.suse = Suse.__new__(Suse)
        self.suse._node = self.node
        self.log = MagicMock()
        self.suse._log = self.log
        wait_patch = patch.object(self.suse, "wait_running_process")
        self.wait = wait_patch.start()
        self.addCleanup(wait_patch.stop)
        sleep_patch = patch("lisa.operating_system.time.sleep")
        self.sleep = sleep_patch.start()
        self.addCleanup(sleep_patch.stop)

    def _result(
        self, exit_code: int = 0, stdout: str = "", stderr: str = ""
    ) -> ExecutableResult:
        return ExecutableResult(
            _stdout=stdout,
            _stderr=stderr,
            exit_code=exit_code,
            cmd="zypper",
            _id_="test",
            elapsed=0,
        )

    def _plugin_timeout(self, service_pack: str = "SP6") -> str:
        package = (
            "libisl15-0.18-1.443.x86_64.rpm"
            if service_pack == "SP6"
            else "libltdl7-2.4.6-150000.3.8.1.x86_64.rpm"
        )
        return (
            "[Basesystem_Module_x86_64:"
            f"SLE-Module-Basesystem15-{service_pack}-Pool|"
            "plugin:/susecloud?credentials=Basesystem_Module_x86_64"
            "&path=/repo/SUSE/Products/SLE-Module-Basesystem/"
            f"15-{service_pack}/x86_64/product/] Can't provide file '{package}'\n"
            "History:\n - Not ready to read within timeout.\n"
            "Installation has been aborted as directed."
        )

    def test_install_retries_observed_sp6_and_sp7_timeouts(self) -> None:
        for service_pack in ("SP6", "SP7"):
            with self.subTest(service_pack=service_pack):
                self.node.reset_mock()
                self.sleep.reset_mock()
                self.wait.reset_mock()
                self.node.execute.side_effect = [
                    self._result(8, self._plugin_timeout(service_pack)),
                    self._result(),
                ]

                self.suse._install_packages(
                    ["gcc"],
                    signed=False,
                    timeout=123,
                    extra_args=["--download-in-advance"],
                )

                self.assertEqual(2, self.node.execute.call_count)
                self.assertEqual(
                    self.node.execute.call_args_list[0],
                    self.node.execute.call_args_list[1],
                )
                self.assertEqual(123, self.node.execute.call_args.kwargs["timeout"])
                command = self.node.execute.call_args.args[0]
                self.assertIn("--no-gpg-checks", command)
                self.assertIn("--download-in-advance", command)
                self.assertNotIn("--force-resolution", command)
                self.sleep.assert_called_once_with(10)
                self.assertEqual([call("zypper")] * 2, self.wait.call_args_list)

    def test_retries_timeout_split_between_stdout_and_stderr(self) -> None:
        self.node.execute.side_effect = [
            self._result(
                8,
                "plugin:/susecloud?credentials=Basesystem_Module_x86_64",
                "Not ready to read within timeout.",
            ),
            self._result(),
        ]

        self.suse._install_packages(["gcc"])

        self.assertEqual(2, self.node.execute.call_count)
        self.sleep.assert_called_once_with(10)

    def test_persistent_timeout_is_bounded_and_preserves_output(self) -> None:
        self.node.execute.return_value = self._result(
            8, self._plugin_timeout(), "plugin diagnostic"
        )

        with self.assertRaises(LisaException) as raised:
            self.suse._install_packages(["gcc"])

        self.assertEqual(5, self.node.execute.call_count)
        self.assertEqual([call(10)] * 4, self.sleep.call_args_list)
        self.assertIn("plugin read timeout", str(raised.exception))
        self.assertIn("5 attempts", str(raised.exception))
        self.assertIn("libisl15", str(raised.exception))
        self.assertIn("plugin diagnostic", str(raised.exception))

    def test_success_on_last_attempt(self) -> None:
        self.node.execute.side_effect = [
            self._result(8, self._plugin_timeout())
        ] * 4 + [self._result()]

        self.suse._install_packages(["gcc"])

        self.assertEqual(5, self.node.execute.call_count)
        self.assertEqual([call(10)] * 4, self.sleep.call_args_list)

    def test_unrelated_commit_errors_are_not_retried(self) -> None:
        failures = (
            "package script failed",
            "Not ready to read within timeout.",
            "plugin:/another-plugin?path=/repo\nNot ready to read within timeout.",
            "plugin:/susecloud?path=/repo\nHTTP response: 404 Not Found",
            "plugin:/susecloud?path=/repo\nCredentials are invalid",
        )
        for output in failures:
            with self.subTest(output=output):
                self.node.reset_mock()
                self.node.execute.return_value = self._result(8, output)
                self.log.reset_mock()

                with self.assertRaises(LisaException):
                    self.suse._install_packages(["gcc"])

                self.node.execute.assert_called_once()
                self.sleep.assert_not_called()
                self.log.warning.assert_not_called()

    def test_success_with_timeout_text_is_not_retried(self) -> None:
        self.node.execute.return_value = self._result(0, self._plugin_timeout())

        self.suse._install_packages(["gcc"])

        self.node.execute.assert_called_once()
        self.sleep.assert_not_called()

    def test_existing_lock_retries_are_preserved(self) -> None:
        self.node.execute.side_effect = [
            self._result(7, "System management is locked"),
            self._result(
                8,
                stderr=(
                    "can't create transaction lock on "
                    "/usr/lib/sysimage/rpm/.rpm.lock"
                ),
            ),
            self._result(),
        ]

        self.suse._install_packages(["gcc"])

        self.assertEqual(3, self.node.execute.call_count)
        self.assertEqual([call(10)] * 2, self.sleep.call_args_list)

    def test_mixed_retryable_errors_share_one_budget(self) -> None:
        self.node.execute.side_effect = [
            self._result(7),
            self._result(8, self._plugin_timeout()),
            self._result(7),
            self._result(8, self._plugin_timeout()),
            self._result(7),
        ]

        with self.assertRaises(LisaException) as raised:
            self.suse._install_packages(["gcc"])

        self.assertEqual(5, self.node.execute.call_count)
        self.assertEqual([call(10)] * 4, self.sleep.call_args_list)
        self.assertIn("lock contention", str(raised.exception))

    def test_nonretryable_error_after_timeout_stops_immediately(self) -> None:
        self.node.execute.side_effect = [
            self._result(8, self._plugin_timeout()),
            self._result(8, "RPM script failed"),
        ]

        with self.assertRaisesRegex(LisaException, "RPM script failed"):
            self.suse._install_packages(["gcc"])

        self.assertEqual(2, self.node.execute.call_count)
        self.sleep.assert_called_once_with(10)

    def test_missing_package_is_not_retried(self) -> None:
        self.node.execute.return_value = self._result(104, "No provider found")

        with self.assertRaises(MissingPackagesException):
            self.suse._install_packages(["missing-package"])

        self.node.execute.assert_called_once()
        self.sleep.assert_not_called()

    def test_existing_force_resolution_is_preserved(self) -> None:
        self.node.execute.side_effect = [
            self._result(4, "Dependency conflict"),
            self._result(),
        ]

        self.suse._install_packages(["gcc"])

        self.assertEqual(2, self.node.execute.call_count)
        self.assertIn("--force-resolution", self.node.execute.call_args.args[0])
        self.sleep.assert_not_called()

    def test_update_uses_same_retry_handling(self) -> None:
        self.node.execute.side_effect = [
            self._result(8, self._plugin_timeout()),
            self._result(),
        ]

        self.suse._update_packages(["gcc"])

        self.assertEqual(2, self.node.execute.call_count)
        self.assertEqual(
            self.node.execute.call_args_list[0], self.node.execute.call_args_list[1]
        )
        self.sleep.assert_called_once_with(10)
