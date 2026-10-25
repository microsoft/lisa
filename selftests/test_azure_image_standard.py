# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import List
from unittest import TestCase
from unittest.mock import MagicMock

from semver import VersionInfo

from lisa.microsoft.testsuites.core.azure_image_standard import AzureImageStandard
from lisa.operating_system import CBLMariner, RPMRepositoryInfo


class RepositoryInstalledTestCase(TestCase):
    def _verify_repositories(self, major: int, repository_ids: List[str]) -> None:
        os = MagicMock(spec=CBLMariner)
        os.information.version = VersionInfo(major, 0, 0)
        os.get_repositories.return_value = [
            RPMRepositoryInfo(id=repo_id, name=repo_id) for repo_id in repository_ids
        ]
        node = MagicMock(os=os)

        AzureImageStandard.verify_repository_installed(MagicMock(), node)

        os.get_repositories.assert_called_once_with()

    def test_azure_linux_4_production_repositories(self) -> None:
        self._verify_repositories(4, ["azurelinux-base", "azurelinux-microsoft"])

    def test_azure_linux_4_cloud_image_repositories(self) -> None:
        self._verify_repositories(
            4,
            [
                "azurelinux-base",
                "azurelinux-cloud-native",
                "azurelinux-microsoft",
                "azurelinux-preview-base",
                "azurelinux-preview-cloud-native",
                "azurelinux-preview-microsoft",
            ],
        )

    def test_azure_linux_4_missing_required_repository(self) -> None:
        repositories = ["azurelinux-base", "azurelinux-microsoft"]
        for missing in repositories:
            with self.subTest(missing=missing):
                with self.assertRaisesRegex(
                    AssertionError, f"{missing} repository should be present"
                ):
                    self._verify_repositories(
                        4, [repo for repo in repositories if repo != missing]
                    )

    def test_azure_linux_4_requires_exact_production_ids(self) -> None:
        for replacement in [
            "azurelinux-preview-base",
            "azurelinux-base-extra",
            "custom-azurelinux-base",
        ]:
            with self.subTest(replacement=replacement):
                with self.assertRaisesRegex(
                    AssertionError, "azurelinux-base repository should be present"
                ):
                    self._verify_repositories(4, [replacement, "azurelinux-microsoft"])

    def test_azure_linux_4_rejects_older_repository_names(self) -> None:
        for repositories in [
            ["mariner-official-base", "mariner-official-microsoft"],
            [
                "azurelinux-official-base",
                "azurelinux-official-ms-non-oss",
                "azurelinux-official-ms-oss",
            ],
        ]:
            with self.subTest(repositories=repositories):
                with self.assertRaisesRegex(
                    AssertionError, "azurelinux-base repository should be present"
                ):
                    self._verify_repositories(4, repositories)

    def test_legacy_repository_expectations_are_preserved(self) -> None:
        expected = {
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
        }
        for major, repositories in expected.items():
            for suffix in ["", "/x86_64"]:
                with self.subTest(major=major, suffix=suffix):
                    self._verify_repositories(
                        major, [repo + suffix for repo in repositories]
                    )
            for missing in repositories:
                with self.subTest(major=major, missing=missing):
                    with self.assertRaisesRegex(
                        AssertionError, f"{missing} repository should be present"
                    ):
                        self._verify_repositories(
                            major, [repo for repo in repositories if repo != missing]
                        )

    def test_empty_repository_list_fails(self) -> None:
        for major in [1, 2, 3, 4]:
            with self.subTest(major=major):
                with self.assertRaises(AssertionError):
                    self._verify_repositories(major, [])
