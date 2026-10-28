# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import fnmatch
import shlex
from types import SimpleNamespace
from typing import Any, Dict, cast
from unittest import TestCase
from unittest.mock import MagicMock, call, patch

from lisa.base_tools import Cat, Sed, Service
from lisa.executable import Tools
from lisa.tools import Ssh, Sshd
from lisa.util import LisaException
from lisa.util.logger import get_logger
from lisa.util.shell import SshShell


class SshTestCase(TestCase):
    def setUp(self) -> None:
        self.ssh = Ssh.__new__(Ssh)
        self.node = MagicMock()
        self.node.shell = MagicMock(spec=SshShell)
        self.ssh.node = self.node
        self.ssh._log = MagicMock()
        self.cat = MagicMock(spec=Cat)
        self.sed = MagicMock(spec=Sed)
        self.service = MagicMock(spec=Service)
        self.node.tools = {Cat: self.cat, Sed: self.sed, Service: self.service}
        self.config_path = "/etc/ssh/sshd_config"
        config_path = patch.object(
            self.ssh, "get_default_sshd_config_path", return_value=self.config_path
        )
        config_path.start()
        self.addCleanup(config_path.stop)

    def test_max_sessions_precedes_existing_settings_and_includes(self) -> None:
        self.ssh.set_max_session(count=300)

        self.sed.insert_line_beginning.assert_called_once_with(
            "MaxSessions 300", self.config_path, sudo=True
        )
        self.sed.append.assert_not_called()
        self.service.restart_service.assert_called_once_with("sshd")
        self.node.close.assert_called_once_with()

    def test_max_sessions_preserves_default_and_ssh_service_fallback(self) -> None:
        self.service.check_service_exists.side_effect = [False, True]

        self.ssh.set_max_session()

        self.sed.insert_line_beginning.assert_called_once_with(
            "MaxSessions 200", self.config_path, sudo=True
        )
        self.service.restart_service.assert_called_once_with("ssh")
        self.node.close.assert_called_once_with()

    def test_max_sessions_overrides_explicit_and_included_lower_limits(self) -> None:
        for existing, expected_limit in (
            ("MaxSessions 10", "10"),
            ("Include /etc/ssh/sshd_config.d/limits.conf", "5"),
        ):
            with self.subTest(existing=existing):
                self._assert_max_sessions_overrides_lower_limit(
                    existing, expected_limit
                )

    def _assert_max_sessions_overrides_lower_limit(
        self, existing: str, expected_limit: str
    ) -> None:
        config = [existing, "Match User restricted", "    MaxSessions 1"]
        original_config = list(config)

        def insert(line: str, file: str, sudo: bool = False) -> None:
            config.insert(0, line)

        def effective_config(*args: Any, **kwargs: Any) -> SimpleNamespace:
            # Model sshd's first-value-wins rule, including an Include.
            expanded = "\n".join(config).replace(
                "Include /etc/ssh/sshd_config.d/limits.conf", "MaxSessions 5"
            )
            first = next(
                line
                for line in expanded.splitlines()
                if line.startswith("MaxSessions ")
            )
            return SimpleNamespace(
                exit_code=0, stdout=f"maxsessions {first.split()[1]}\n"
            )

        self.sed.insert_line_beginning.side_effect = insert
        self.node.execute.side_effect = effective_config
        self.assertEqual(expected_limit, self.ssh.get("MaxSessions"))

        self.ssh.set_max_session(count=200)

        self.assertEqual("200", self.ssh.get("MaxSessions"))
        self.assertEqual(original_config, config[1:])

    def test_config_write_failure_does_not_restart_or_close(self) -> None:
        self.sed.insert_line_beginning.side_effect = LisaException("write failed")

        with self.assertRaisesRegex(LisaException, "write failed"):
            self.ssh.set_max_session()

        self.service.restart_service.assert_not_called()
        self.node.close.assert_not_called()

    def test_missing_service_fails_without_closing_connection(self) -> None:
        self.service.check_service_exists.return_value = False

        with self.assertRaisesRegex(LisaException, "could not find ssh or sshd"):
            self.ssh.set_max_session()

        self.service.restart_service.assert_not_called()
        self.node.close.assert_not_called()

    def test_restart_failure_is_propagated(self) -> None:
        self.service.restart_service.side_effect = LisaException("restart failed")

        with self.assertRaisesRegex(LisaException, "restart failed"):
            self.ssh.set_max_session()

        self.node.close.assert_not_called()

    def _use_fallback_config(self, files: Dict[str, str]) -> None:
        self.cat.read.side_effect = lambda path, *args, **kwargs: files[
            shlex.split(path)[0]
        ]

        def execute(command: str, **kwargs: Any) -> SimpleNamespace:
            if command.startswith("printf '%s'"):
                return SimpleNamespace(
                    exit_code=0,
                    stdout="192.0.2.10 54321 198.51.100.20 22",
                    stderr="",
                )
            if command.startswith("sshd -T"):
                return SimpleNamespace(
                    exit_code=1,
                    stdout="",
                    stderr="Missing privilege separation directory",
                )
            self.assertTrue(command.startswith("for config in "))
            pattern = shlex.split(command)[3].rstrip(";")
            paths = [path for path in files if fnmatch.fnmatchcase(path, pattern)]
            return SimpleNamespace(
                exit_code=0, stdout="\0".join(reversed(paths)), stderr=""
            )

        self.node.execute.side_effect = execute

    def test_fallback_setter_getter_preserves_first_value_precedence(self) -> None:
        files = {self.config_path: "MaxSessions 10\nMaxSessions 5\n"}
        self._use_fallback_config(files)

        def insert(line: str, file: str, sudo: bool = False) -> None:
            files[file] = line + "\n" + files[file]

        self.sed.insert_line_beginning.side_effect = insert
        self.assertEqual("10", self.ssh.get("MaxSessions"))

        self.ssh.set_max_session(count=200)

        self.assertEqual("200", self.ssh.get("MaxSessions"))

    def test_fallback_missing_max_sessions_can_be_set_explicitly(self) -> None:
        files = {self.config_path: "#MaxSessions 10\n"}
        self._use_fallback_config(files)
        self.node.shell.connection_info = SimpleNamespace(username="lisa")

        def insert(line: str, file: str, sudo: bool = False) -> None:
            files[file] = line + "\n" + files[file]

        self.sed.insert_line_beginning.side_effect = insert
        self.assertEqual("", self.ssh.get("MaxSessions", connection_context=True))

        self.ssh.set_max_session(count=200)

        self.assertEqual("200", self.ssh.get("MaxSessions", connection_context=True))

    def test_get_uses_active_connection_context(self) -> None:
        self.node.shell.connection_info = SimpleNamespace(username="lisa")
        self.node.execute.side_effect = [
            SimpleNamespace(
                exit_code=0,
                stdout="192.0.2.10 54321 198.51.100.20 22",
                stderr="",
            ),
            SimpleNamespace(exit_code=0, stdout="maxsessions 12\n", stderr=""),
        ]

        self.assertEqual("12", self.ssh.get("MaxSessions", connection_context=True))

        self.node.execute.assert_has_calls(
            [
                call("printf '%s' \"${SSH_CONNECTION:-}\""),
                call(
                    "sshd -T -C "
                    "user=lisa,addr=192.0.2.10,laddr=198.51.100.20,lport=22",
                    sudo=True,
                ),
            ]
        )

    def test_fallback_expands_includes_at_their_position_in_sorted_order(self) -> None:
        files = {
            self.config_path: (
                "Include sshd_config.d/*.conf\n"
                "MaxSessions 10\n"
                "Match User restricted\n    MaxSessions 1\n"
            ),
            "/etc/ssh/sshd_config.d/10-limits.conf": "mAxSeSsIoNs 5 # comment\n",
            "/etc/ssh/sshd_config.d/20-limits.conf": "MaxSessions 8\n",
        }
        self._use_fallback_config(files)
        self.assertEqual("5", self.ssh.get("MaxSessions"))

        files[self.config_path] = "MaxSessions 200\n" + files[self.config_path]
        self.assertEqual("200", self.ssh.get("MaxSessions"))

    def test_fallback_does_not_read_match_settings_as_global(self) -> None:
        self._use_fallback_config(
            {self.config_path: "Match User restricted\n    MaxSessions 1\n"}
        )
        self.assertEqual("", self.ssh.get("MaxSessions"))

    def test_fallback_supports_nested_quoted_and_unmatched_includes(self) -> None:
        self._use_fallback_config(
            {
                self.config_path: (
                    "Include /etc/ssh/missing/*.conf '/etc/ssh/sub dir/*.conf'\n"
                    "MaxSessions 10\n"
                ),
                "/etc/ssh/sub dir/limits.conf": "Include nested.conf\n",
                "/etc/ssh/nested.conf": "MaxSessions = 6\n",
            }
        )
        self.assertEqual("6", self.ssh.get("MaxSessions"))

    def test_fallback_preserves_multiple_include_pattern_order(self) -> None:
        self._use_fallback_config(
            {
                self.config_path: (
                    "Include /etc/ssh/20-limits.conf /etc/ssh/10-limits.conf\n"
                ),
                "/etc/ssh/10-limits.conf": "MaxSessions 5\n",
                "/etc/ssh/20-limits.conf": "MaxSessions 8\n",
            }
        )
        self.assertEqual("8", self.ssh.get("MaxSessions"))

    def test_fallback_preserves_negated_include_patterns(self) -> None:
        self._use_fallback_config(
            {
                self.config_path: "Include /etc/ssh/[!0-9]*.conf\n",
                "/etc/ssh/limits.conf": "MaxSessions 5\n",
                "/etc/ssh/10-limits.conf": "MaxSessions 8\n",
            }
        )

        self.assertEqual("5", self.ssh.get("MaxSessions"))

    def test_connection_context_fallback_rejects_match_blocks(self) -> None:
        self._use_fallback_config(
            {
                self.config_path: (
                    "MaxSessions 200\nMatch User restricted\nMaxSessions 5\n"
                )
            }
        )
        self.node.shell.connection_info = SimpleNamespace(username="lisa")
        self.node.execute.side_effect = [
            SimpleNamespace(stdout="192.0.2.10 54321 198.51.100.20 22"),
            SimpleNamespace(
                exit_code=1,
                stdout="",
                stderr="Missing privilege separation directory",
            ),
        ]

        with self.assertRaisesRegex(LisaException, "configuration contains Match"):
            self.ssh.get("MaxSessions", connection_context=True)

    def test_fallback_propagates_config_read_failure(self) -> None:
        self._use_fallback_config({self.config_path: "MaxSessions 10\n"})
        self.cat.read.side_effect = LisaException("configuration read denied")

        with self.assertRaisesRegex(LisaException, "configuration read denied"):
            self.ssh.get("MaxSessions")

    def test_fallback_rejects_recursive_includes(self) -> None:
        self._use_fallback_config({self.config_path: "Include /etc/ssh/sshd_config\n"})
        with self.assertRaisesRegex(LisaException, "Include.*depth"):
            self.ssh.get("MaxSessions")

    def test_server_tool_does_not_require_outbound_client(self) -> None:
        def execute(command: str, **kwargs: Any) -> SimpleNamespace:
            self.assertEqual("command -v sshd", command)
            return SimpleNamespace(exit_code=0, stdout="/usr/sbin/sshd", stderr="")

        node = SimpleNamespace(
            log=get_logger("ssh-server-test"),
            is_posix=True,
            os=SimpleNamespace(name="Linux"),
            execute=execute,
        )
        tool = Tools(cast(Any, node))[Sshd]
        self.assertEqual("sshd", tool.command)
        self.assertFalse(tool.can_install)
