# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import PurePosixPath
from types import SimpleNamespace
from typing import Any, Dict, List, Type, cast
from unittest import TestCase
from unittest.mock import MagicMock, call, patch

from lisa.sut_orchestrator.openvmm.installer import OpenVmmSourceInstaller
from lisa.sut_orchestrator.openvmm.schema import OpenVmmSourceInstallerSchema
from lisa.sut_orchestrator.openvmm.transformers import (
    OpenVmmInstallerTransformer,
    OpenVmmInstallerTransformerSchema,
)
from lisa.tools import Cargo, Git, Ln, Rm
from lisa.util import LisaException, subclasses


class _ToolMap:
    def __init__(self, mapping: Dict[Any, Any]) -> None:
        self._mapping = mapping

    def __getitem__(self, key: Type[Any]) -> Any:
        return self._mapping[key]


class Ubuntu:
    def __init__(self, package_installs: List[List[str]]) -> None:
        self._package_installs = package_installs

    def install_packages(self, packages: List[str]) -> None:
        self._package_installs.append(packages)


class OpenVmmInstallerTestCase(TestCase):
    def test_source_installer_uses_host_paths_for_remote_commands(self) -> None:
        package_installs: List[List[str]] = []
        linux = Ubuntu(package_installs)

        def _wrap_with_rustup_lock(command: str) -> str:
            return f"locked({command})"

        cargo = SimpleNamespace(
            exists=True,
            command="cargo",
            toolchain="stable",
            wrap_with_rustup_lock=_wrap_with_rustup_lock,
        )
        git = SimpleNamespace(
            clone=MagicMock(return_value="/tmp/work/openvmm"),
            get_current_commit_hash=MagicMock(return_value="abc1234"),
        )
        ln = SimpleNamespace(create_link=MagicMock())
        rm = SimpleNamespace(remove_directory=MagicMock())
        executed_commands: List[Dict[str, Any]] = []

        def _execute(command: str, **kwargs: Any) -> SimpleNamespace:
            executed_commands.append({"command": command, **kwargs})
            if command == "echo $HOME":
                return SimpleNamespace(stdout="/home/test\n", stderr="", exit_code=0)
            if command == "command -v cargo":
                return SimpleNamespace(
                    stdout="/home/test/.cargo/bin/cargo\n",
                    stderr="",
                    exit_code=0,
                )
            if command == "/usr/local/bin/openvmm --version":
                return SimpleNamespace(stdout="openvmm 1.0.0\n", stderr="", exit_code=0)
            return SimpleNamespace(stdout="", stderr="", exit_code=0)

        node = SimpleNamespace(
            os=linux,
            working_path=PurePosixPath("/tmp/work"),
            execute=_execute,
            get_pure_path=PurePosixPath,
            get_str_path=str,
            tools=_ToolMap({Cargo: cargo, Git: git, Ln: ln, Rm: rm}),
        )
        runbook = OpenVmmSourceInstallerSchema(
            repo="https://github.com/microsoft/openvmm.git",
            install_path="/usr/local/bin/openvmm",
        )
        installer = OpenVmmSourceInstaller(
            runbook=runbook,
            node=cast(Any, node),
            log=MagicMock(),
        )

        version = installer.install()

        self.assertEqual("openvmm 1.0.0", version)
        self.assertTrue(package_installs)
        restore_call = next(
            command
            for command in executed_commands
            if "xflowey restore-packages" in command["command"]
        )
        self.assertEqual(
            {
                "OPENSSL_NO_VENDOR": "1",
                "PATH": "/home/test/.cargo/bin:$PATH",
                "RUSTC": "/home/test/.cargo/bin/rustc",
                "RUSTDOC": "/home/test/.cargo/bin/rustdoc",
            },
            restore_call["update_envs"],
        )
        rust_src_call = next(
            command
            for command in executed_commands
            if "component add rust-src" in command["command"]
        )
        self.assertTrue(rust_src_call["command"].startswith("locked("))
        rm.remove_directory.assert_called_once_with("/tmp/work/openvmm")
        git.clone.assert_called_once_with(
            url="https://github.com/microsoft/openvmm.git",
            cwd=PurePosixPath("/tmp/work"),
            dir_name="openvmm",
            ref="",
            auth_token="",
        )
        install_dir_call = next(
            command
            for command in executed_commands
            if command["command"].startswith("mkdir -p /usr/local/bin")
        )
        self.assertTrue(install_dir_call["sudo"])
        copy_call = next(
            command
            for command in executed_commands
            if command["command"].startswith("cp ")
        )
        self.assertIn("/tmp/work/openvmm/target/release/openvmm", copy_call["command"])
        self.assertNotIn("\\", copy_call["command"])

    def test_source_installer_refreshes_stale_source_checkout(self) -> None:
        package_installs: List[List[str]] = []
        linux = Ubuntu(package_installs)

        def _wrap_with_rustup_lock(command: str) -> str:
            return f"locked({command})"

        cargo = SimpleNamespace(
            exists=True,
            command="cargo",
            toolchain="stable",
            wrap_with_rustup_lock=_wrap_with_rustup_lock,
        )
        git = SimpleNamespace(
            clone=MagicMock(return_value="/tmp/work/openvmm"),
            get_current_commit_hash=MagicMock(return_value="abc1234"),
        )
        ln = SimpleNamespace(create_link=MagicMock())
        rm = SimpleNamespace(remove_directory=MagicMock())
        executed_commands: List[Dict[str, Any]] = []

        def _execute(command: str, **kwargs: Any) -> SimpleNamespace:
            executed_commands.append({"command": command, **kwargs})
            if command == "echo $HOME":
                return SimpleNamespace(stdout="/home/test\n", stderr="", exit_code=0)
            if command == "command -v cargo":
                return SimpleNamespace(
                    stdout="/home/test/.cargo/bin/cargo\n",
                    stderr="",
                    exit_code=0,
                )
            if command == "/usr/local/bin/openvmm --version":
                return SimpleNamespace(stdout="openvmm 1.0.0\n", stderr="", exit_code=0)
            return SimpleNamespace(stdout="", stderr="", exit_code=0)

        node = SimpleNamespace(
            os=linux,
            working_path=PurePosixPath("/tmp/work"),
            execute=_execute,
            get_pure_path=PurePosixPath,
            get_str_path=str,
            tools=_ToolMap({Cargo: cargo, Git: git, Ln: ln, Rm: rm}),
        )
        runbook = OpenVmmSourceInstallerSchema(
            repo="https://github.com/microsoft/openvmm.git",
            install_path="/usr/local/bin/openvmm",
        )
        installer = OpenVmmSourceInstaller(
            runbook=runbook,
            node=cast(Any, node),
            log=MagicMock(),
        )

        version = installer.install()

        self.assertEqual("openvmm 1.0.0", version)
        rm.remove_directory.assert_called_once_with("/tmp/work/openvmm")
        git.clone.assert_called_once_with(
            url="https://github.com/microsoft/openvmm.git",
            cwd=PurePosixPath("/tmp/work"),
            dir_name="openvmm",
            ref="",
            auth_token="",
        )
        restore_calls = [
            command
            for command in executed_commands
            if "xflowey restore-packages" in command["command"]
        ]
        self.assertEqual(1, len(restore_calls))


class OpenVmmInstallerTransformerTestCase(TestCase):
    def _create_transformer(self, force_install: bool = False) -> tuple[Any, MagicMock]:
        installer_runbook = OpenVmmSourceInstallerSchema(
            install_path="/usr/local/bin/openvmm",
            force_install=force_install,
        )
        installer = MagicMock()
        installer.runbook = installer_runbook
        installer.install.return_value = "openvmm 0.2.0"

        transformer = cast(Any, object.__new__(OpenVmmInstallerTransformer))
        transformer.runbook = OpenVmmInstallerTransformerSchema(
            installer=installer_runbook
        )
        transformer._node = SimpleNamespace(name="test-host")
        transformer._log = MagicMock()
        return transformer, installer

    def _run_transformer(self, transformer: Any, installer: MagicMock) -> None:
        with patch.object(
            subclasses.Factory, "create_by_runbook", return_value=installer
        ):
            transformer._internal_run()

    def test_installs_when_only_path_command_is_available(self) -> None:
        transformer, installer = self._create_transformer()
        installer.get_version.side_effect = [
            LisaException("configured path is missing"),
            "openvmm 0.2.0",
            "openvmm 0.2.0",
        ]

        self._run_transformer(transformer, installer)

        installer.validate.assert_called_once_with()
        installer.install.assert_called_once_with()
        self.assertEqual(
            [call("/usr/local/bin/openvmm"), call("/usr/local/bin/openvmm"), call()],
            installer.get_version.call_args_list,
        )

    def test_skips_install_when_configured_path_is_available(self) -> None:
        transformer, installer = self._create_transformer()
        installer.get_version.return_value = "openvmm 0.2.0"

        self._run_transformer(transformer, installer)

        installer.validate.assert_not_called()
        installer.install.assert_not_called()
        self.assertEqual(
            [call("/usr/local/bin/openvmm"), call("/usr/local/bin/openvmm"), call()],
            installer.get_version.call_args_list,
        )

    def test_installs_when_configured_path_and_path_are_missing(self) -> None:
        transformer, installer = self._create_transformer()
        installer.get_version.side_effect = [
            LisaException("configured path is missing"),
            "openvmm 0.2.0",
            LisaException("PATH command is missing"),
        ]

        self._run_transformer(transformer, installer)

        installer.install.assert_called_once_with()
        transformer._log.warning.assert_called_once()

    def test_force_install_reinstalls_existing_configured_binary(self) -> None:
        transformer, installer = self._create_transformer(force_install=True)
        installer.get_version.return_value = "openvmm 0.2.0"

        self._run_transformer(transformer, installer)

        installer.validate.assert_called_once_with()
        installer.install.assert_called_once_with()
