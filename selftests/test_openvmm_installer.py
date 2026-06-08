# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import PurePosixPath
from types import SimpleNamespace
from typing import Any, Dict, List, Type, cast
from unittest import TestCase
from unittest.mock import MagicMock

from lisa.sut_orchestrator.openvmm.installer import OpenVmmSourceInstaller
from lisa.sut_orchestrator.openvmm.schema import OpenVmmSourceInstallerSchema
from lisa.tools import Cargo, Git, Ln


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
        cargo = SimpleNamespace(
            exists=True,
            command="/home/test/.cargo/bin/cargo",
            toolchain="stable",
        )
        git = SimpleNamespace(clone=MagicMock(return_value="/tmp/work/openvmm-src"))
        ln = SimpleNamespace(create_link=MagicMock())
        executed_commands: List[Dict[str, Any]] = []

        def _execute(command: str, **kwargs: Any) -> SimpleNamespace:
            executed_commands.append({"command": command, **kwargs})
            if command == "echo $HOME":
                return SimpleNamespace(stdout="/home/test\n", stderr="", exit_code=0)
            if command == "/usr/local/bin/openvmm --version":
                return SimpleNamespace(stdout="openvmm 1.0.0\n", stderr="", exit_code=0)
            return SimpleNamespace(stdout="", stderr="", exit_code=0)

        node = SimpleNamespace(
            os=linux,
            working_path=PurePosixPath("/tmp/work"),
            execute=_execute,
            get_pure_path=PurePosixPath,
            get_str_path=str,
            tools=_ToolMap({Cargo: cargo, Git: git, Ln: ln}),
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
        self.assertIn(
            "/tmp/work/openvmm-src/target/release/openvmm", copy_call["command"]
        )
        self.assertNotIn("\\", copy_call["command"])
