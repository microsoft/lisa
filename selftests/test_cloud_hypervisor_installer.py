# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import json
from types import SimpleNamespace
from typing import Any, Dict, List, Tuple
from unittest import TestCase
from unittest.mock import MagicMock, patch

from lisa.base_tools import Uname
from lisa.operating_system import CpuArchitecture, Ubuntu
from lisa.sut_orchestrator.libvirt.transformers import (
    BaseInstallerSchema,
    CloudHypervisorBinaryInstaller,
)
from lisa.tools import Ln, Wget
from lisa.util import LisaException


class CloudHypervisorBinaryInstallerTestCase(TestCase):
    def test_selects_release_asset_for_host_architecture(self) -> None:
        releases = [
            (
                "v53.0",
                [
                    "ch-remote",
                    "ch-remote-static",
                    "cloud-hypervisor-static-aarch64",
                    "cloud-hypervisor-v53.0.tar.xz",
                    "cloud-hypervisor-static",
                ],
                "cloud-hypervisor-static",
            ),
            (
                "v40.0",
                [
                    "cloud-hypervisor-static",
                    "cloud-hypervisor",
                    "cloud-hypervisor-static-aarch64",
                ],
                "cloud-hypervisor",
            ),
        ]
        for tag, assets, x64_asset in releases:
            for architecture, expected_asset in (
                (CpuArchitecture.X64, x64_asset),
                (CpuArchitecture.ARM64, "cloud-hypervisor-static-aarch64"),
            ):
                with self.subTest(tag=tag, architecture=architecture):
                    installer, node, wget = self._create_installer(
                        tag, architecture, self._release(tag, assets)
                    )

                    installer.install()

                    wget.get.assert_called_once_with(
                        url=(
                            "https://github.com/cloud-hypervisor/cloud-hypervisor/"
                            f"releases/download/{tag}/{expected_asset}"
                        ),
                        executable=True,
                        filename="cloud-hypervisor",
                    )
                    node.execute.assert_any_call(
                        "cp /work/cloud-hypervisor /usr/local/bin", sudo=True
                    )
                    node.tools[Ln].create_link.assert_called_once_with(
                        target="/usr/local/bin/cloud-hypervisor",
                        link="/usr/bin/cloud-hypervisor",
                        is_symbolic=True,
                        force=True,
                    )

    def test_latest_is_resolved_once_to_the_returned_release(self) -> None:
        installer, node, wget = self._create_installer(
            "", CpuArchitecture.X64, self._release("v53.0", ["cloud-hypervisor-static"])
        )

        installer.install()

        metadata_calls = [
            call
            for call in node.execute.call_args_list
            if "api.github.com" in call.args[0]
        ]
        self.assertEqual(1, len(metadata_calls))
        self.assertIn("/releases/latest", metadata_calls[0].args[0])
        self.assertIn(
            "/releases/download/v53.0/cloud-hypervisor-static",
            wget.get.call_args.kwargs["url"],
        )

    def test_missing_compatible_binary_does_not_install_other_assets(self) -> None:
        cases: List[Tuple[CpuArchitecture, List[str]]] = [
            (CpuArchitecture.X64, ["cloud-hypervisor-static-aarch64"]),
            (CpuArchitecture.ARM64, ["cloud-hypervisor", "cloud-hypervisor-static"]),
            (
                CpuArchitecture.X64,
                ["ch-remote-static", "cloud-hypervisor-v53.0.tar.xz"],
            ),
            (CpuArchitecture.X64, []),
        ]
        for architecture, assets in cases:
            with self.subTest(architecture=architecture, assets=assets):
                installer, node, wget = self._create_installer(
                    "v53.0", architecture, self._release("v53.0", assets)
                )

                with self.assertRaisesRegex(LisaException, "No .*binary.*v53.0"):
                    installer.install()

                self._assert_not_installed(node, wget)

    def test_unsupported_architecture_does_not_download_x64_binary(self) -> None:
        installer, node, wget = self._create_installer(
            "v53.0",
            CpuArchitecture.I386,
            self._release("v53.0", ["cloud-hypervisor-static"]),
        )

        with self.assertRaisesRegex(LisaException, "architecture.*i386"):
            installer.install()

        self._assert_not_installed(node, wget)

    def test_metadata_failure_does_not_fall_back_to_another_release(self) -> None:
        installer, node, wget = self._create_installer(
            "v53.0", CpuArchitecture.X64, self._release("v53.0", [])
        )
        failure = LisaException("curl: HTTP 403 rate limit exceeded")
        node.execute.side_effect = failure

        with self.assertRaises(LisaException) as raised:
            installer.install()

        self.assertIs(failure, raised.exception)
        node.execute.assert_called_once()
        self._assert_not_installed(node, wget)

    def test_invalid_metadata_fails_before_download(self) -> None:
        invalid_metadata: List[Any] = [
            None,
            {},
            {"tag_name": None, "assets": []},
            {"tag_name": "v53.0", "assets": None},
            self._release("v54.0", ["cloud-hypervisor"]),
        ]
        for metadata in invalid_metadata:
            with self.subTest(metadata=metadata):
                installer, node, wget = self._create_installer(
                    "v53.0", CpuArchitecture.X64, metadata
                )

                with self.assertRaises(LisaException):
                    installer.install()

                self._assert_not_installed(node, wget)

    def test_malformed_json_preserves_the_parse_error(self) -> None:
        installer, node, wget = self._create_installer("v53.0", CpuArchitecture.X64, {})
        node.execute.side_effect = None
        node.execute.return_value = SimpleNamespace(
            stdout="<html>upstream unavailable</html>", exit_code=0
        )

        with self.assertRaises(LisaException) as raised:
            installer.install()

        self.assertIsInstance(raised.exception.__cause__, json.JSONDecodeError)
        self._assert_not_installed(node, wget)

    def test_download_failure_preserves_cause_without_trying_another_asset(
        self,
    ) -> None:
        installer, node, wget = self._create_installer(
            "v40.0",
            CpuArchitecture.X64,
            self._release("v40.0", ["cloud-hypervisor", "cloud-hypervisor-static"]),
        )
        failure = LisaException("HTTP 404 Not Found")
        wget.get.side_effect = failure

        with self.assertRaisesRegex(LisaException, "v40.0.*HTTP 404") as raised:
            installer.install()

        self.assertIs(failure, raised.exception.__cause__)
        wget.get.assert_called_once()
        self.assertFalse(
            any(call.args[0].startswith("cp ") for call in node.execute.call_args_list)
        )
        node.tools[Ln].create_link.assert_not_called()

    def _release(self, tag: str, assets: List[str]) -> Dict[str, Any]:
        return {"tag_name": tag, "assets": [{"name": asset} for asset in assets]}

    def _create_installer(
        self, ref: str, architecture: CpuArchitecture, metadata: Any
    ) -> Tuple[CloudHypervisorBinaryInstaller, MagicMock, MagicMock]:
        node = MagicMock()
        node.os = Ubuntu(node)
        package_installer = patch.object(node.os, "install_packages")
        package_installer.start()
        self.addCleanup(package_installer.stop)
        uname = MagicMock()
        uname.get_machine_architecture.return_value = architecture
        wget = MagicMock()
        wget.get.return_value = "/work/cloud-hypervisor"
        node.tools = {Uname: uname, Wget: wget, Ln: MagicMock()}

        def execute(command: str, **kwargs: Any) -> SimpleNamespace:
            return SimpleNamespace(
                stdout=(
                    json.dumps(metadata)
                    if command.startswith("curl ")
                    else "cloud-hypervisor v53.0"
                ),
                exit_code=0,
            )

        node.execute.side_effect = execute
        installer = CloudHypervisorBinaryInstaller(
            runbook=BaseInstallerSchema(type="binary", ref=ref),
            node=node,
            log=MagicMock(),
        )
        return installer, node, wget

    def _assert_not_installed(self, node: MagicMock, wget: MagicMock) -> None:
        wget.get.assert_not_called()
        self.assertFalse(
            any(call.args[0].startswith("cp ") for call in node.execute.call_args_list)
        )
        node.tools[Ln].create_link.assert_not_called()
