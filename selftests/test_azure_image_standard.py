# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Any, cast
from unittest import TestCase
from unittest.mock import MagicMock

from lisa.microsoft.testsuites.core.azure_image_standard import AzureImageStandard
from lisa.node import Node
from lisa.operating_system import CpuArchitecture, DebianRepositoryInfo, Ubuntu
from lisa.sut_orchestrator import OPENVMM
from lisa.tools import Lscpu


class UbuntuRepositoryTestCase(TestCase):
    def setUp(self) -> None:
        suite_class = cast(Any, AzureImageStandard).__wrapped__
        self.suite = object.__new__(suite_class)

    def _create_node(self, node_type: str, mirror: str) -> MagicMock:
        node = MagicMock(spec=Node)
        node.type_name.return_value = node_type
        node.os = MagicMock(spec=Ubuntu)
        node.os.get_repositories.return_value = [
            DebianRepositoryInfo(
                name=f"jammy-{pocket}",
                status="Hit",
                id=str(index),
                uri=f"http://{mirror}/ubuntu",
                metadata="InRelease",
            )
            for index, pocket in enumerate(("security", "updates"), 1)
        ]
        lscpu = MagicMock(spec=Lscpu)
        lscpu.get_architecture.return_value = CpuArchitecture.X64
        node.tools = MagicMock()
        node.tools.__getitem__.side_effect = {Lscpu: lscpu}.__getitem__
        return node

    def test_openvmm_accepts_upstream_and_azure_ubuntu_archives(self) -> None:
        for mirror in ("archive.ubuntu.com", "azure.archive.ubuntu.com"):
            with self.subTest(mirror=mirror):
                node = self._create_node(OPENVMM, mirror)

                self.suite.verify_repository_installed(node=node)

    def test_azure_remote_nodes_still_require_azure_archive(self) -> None:
        node = self._create_node("remote", "archive.ubuntu.com")

        with self.assertRaises(AssertionError):
            self.suite.verify_repository_installed(node=node)

    def test_openvmm_still_requires_security_and_updates(self) -> None:
        for retained_pocket in ("security", "updates"):
            with self.subTest(retained_pocket=retained_pocket):
                node = self._create_node(OPENVMM, "archive.ubuntu.com")
                node.os.get_repositories.return_value = [
                    repository
                    for repository in node.os.get_repositories.return_value
                    if repository.name == f"jammy-{retained_pocket}"
                ]

                with self.assertRaises(AssertionError):
                    self.suite.verify_repository_installed(node=node)
