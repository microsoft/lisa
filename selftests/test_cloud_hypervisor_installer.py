# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import json
from types import SimpleNamespace
from typing import Any, Dict, List, Tuple
from unittest import TestCase
from unittest.mock import MagicMock, patch

from lisa.base_tools import Uname
from lisa.executable import Tools
from lisa.operating_system import CpuArchitecture, Ubuntu
from lisa.sut_orchestrator.libvirt.transformers import (
    BaseInstallerSchema,
    CloudHypervisorBinaryInstaller,
)
from lisa.tools import Curl, Ln, Wget
from lisa.util import LisaException
from lisa.util.logger import get_logger


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

        node.tools[Curl].run.assert_called_once_with(
            "-fsSL https://api.github.com/repos/cloud-hypervisor/"
            "cloud-hypervisor/releases/latest",
            shell=True,
            force_run=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "Failed to query cloud-hypervisor release 'latest'."
            ),
        )
        self.assertIn(
            "/releases/download/v53.0/cloud-hypervisor-static",
            wget.get.call_args.kwargs["url"],
        )

    def test_installs_curl_before_querying_a_pinned_release(self) -> None:
        metadata = self._release("v53.0", ["cloud-hypervisor-static"])
        installer, node, _ = self._create_installer(
            "v53.0", CpuArchitecture.X64, metadata
        )
        node.log = get_logger("test")
        node.is_posix = True
        node.tools = Tools(node)
        node.execute.side_effect = LisaException("curl: command not found")

        with patch.object(node.os, "install_packages") as install_packages:

            def query_release(*_args: Any, **_kwargs: Any) -> SimpleNamespace:
                install_packages.assert_called_once_with("curl")
                return SimpleNamespace(stdout=json.dumps(metadata), exit_code=0)

            with patch.object(
                Curl, "_check_exists", side_effect=lambda: install_packages.called
            ), patch.object(Curl, "run", side_effect=query_release) as query:
                self.assertEqual(
                    ("v53.0", ["cloud-hypervisor-static"]),
                    installer._get_release(),
                )

                query.assert_called_once_with(
                    "-fsSL https://api.github.com/repos/cloud-hypervisor/"
                    "cloud-hypervisor/releases/tags/v53.0",
                    shell=True,
                    force_run=True,
                    expected_exit_code=0,
                    expected_exit_code_failure_message=(
                        "Failed to query cloud-hypervisor release 'v53.0'."
                    ),
                )
        node.execute.assert_not_called()

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
        node.tools[Curl].run.side_effect = failure

        with self.assertRaises(LisaException) as raised:
            installer.install()

        self.assertIs(failure, raised.exception)
        node.tools[Curl].run.assert_called_once()
        node.execute.assert_not_called()
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
        node.tools[Curl].run.return_value = SimpleNamespace(
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
        curl = MagicMock()
        curl.run.return_value = SimpleNamespace(
            stdout=json.dumps(metadata), exit_code=0
        )
        node.tools = {Uname: uname, Wget: wget, Ln: MagicMock(), Curl: curl}
        node.execute.return_value = SimpleNamespace(
            stdout="cloud-hypervisor v53.0", exit_code=0
        )
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
