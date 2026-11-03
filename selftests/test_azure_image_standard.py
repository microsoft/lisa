# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from inspect import unwrap
from typing import Dict, List, Type, cast
from unittest import TestCase
from unittest.mock import MagicMock

from lisa import Node
from lisa.microsoft.testsuites.core.azure_image_standard import AzureImageStandard
from lisa.operating_system import CBLMariner, RPMRepositoryInfo


class AzureImageStandardTestCase(TestCase):
    _repository_ids: Dict[int, List[str]] = {
        1: [
            "mariner-official-base",
            "mariner-official-microsoft",
            "mariner-official-update",
        ],
        2: [
            "mariner-official-base",
            "mariner-official-microsoft",
            "mariner-official-extras",
        ],
        3: [
            "azurelinux-official-base",
            "azurelinux-official-ms-non-oss",
            "azurelinux-official-ms-oss",
        ],
        4: [
            "azurelinux-base",
            "azurelinux-cloud-native",
            "azurelinux-microsoft",
        ],
    }

    def setUp(self) -> None:
        suite_type = cast(Type[AzureImageStandard], unwrap(AzureImageStandard))
        self.suite = suite_type.__new__(suite_type)
        self.node = MagicMock(spec=Node)
        self.node.os = MagicMock(spec=CBLMariner)

    def _set_repositories(self, major: int, repository_ids: List[str]) -> None:
        self.node.os.information.version.major = major
        self.node.os.get_repositories.return_value = [
            RPMRepositoryInfo(id=repo_id, name=repo_id) for repo_id in repository_ids
        ]

    def test_verify_repository_installed_accepts_version_specific_repositories(
        self,
    ) -> None:
        for major, repository_ids in self._repository_ids.items():
            with self.subTest(major=major):
                self._set_repositories(major, repository_ids)
                self.suite.verify_repository_installed(node=self.node)

    def test_verify_repository_installed_rejects_missing_repositories(self) -> None:
        for major, repository_ids in self._repository_ids.items():
            for missing_id in repository_ids:
                with self.subTest(major=major, missing_id=missing_id):
                    self._set_repositories(
                        major, [repo for repo in repository_ids if repo != missing_id]
                    )
                    with self.assertRaisesRegex(
                        AssertionError, f"{missing_id} repository should be present"
                    ):
                        self.suite.verify_repository_installed(node=self.node)

    def test_verify_repository_installed_rejects_preview_only_repositories(
        self,
    ) -> None:
        self._set_repositories(
            4,
            [
                "azurelinux-preview-base",
                "azurelinux-preview-cloud-native",
                "azurelinux-preview-microsoft",
            ],
        )
        with self.assertRaisesRegex(
            AssertionError, "azurelinux-base repository should be present"
        ):
            self.suite.verify_repository_installed(node=self.node)
