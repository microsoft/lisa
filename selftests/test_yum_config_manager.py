# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from unittest import TestCase
from unittest.mock import MagicMock, patch

from lisa.base_tools.yum_config_manager import YumConfigManager, _repo_id_from_url


class YumConfigManagerTestCase(TestCase):
    def _create_tool(self) -> YumConfigManager:
        tool = YumConfigManager.__new__(YumConfigManager)
        tool.node = MagicMock()
        return tool

    def test_repo_id_from_url(self) -> None:
        self.assertEqual(
            _repo_id_from_url("https://example.com/testrepo/"),
            "example.com_testrepo_",
        )
        self.assertEqual(
            _repo_id_from_url("https://packages.microsoft.com/yumrepos/azurecore/"),
            "packages.microsoft.com_yumrepos_azurecore_",
        )
        self.assertEqual(
            _repo_id_from_url("ftp://mirrors.kernel.org/centos/7/os/x86_64/"),
            "mirrors.kernel.org_centos_7_os_x86_64_",
        )

    def test_add_repository_sets_gpgcheck_when_no_gpgcheck(self) -> None:
        tool = self._create_tool()
        with patch.object(YumConfigManager, "run") as mock_run:
            tool.add_repository("https://packages.microsoft.com/yumrepos/azurecore/")

        tool.node.execute.assert_called_once()
        cmd = tool.node.execute.call_args.kwargs["cmd"]
        self.assertIn("--add-repo", cmd)
        self.assertIn("--nogpgcheck", cmd)
        mock_run.assert_called_once_with(
            "--save --setopt=packages.microsoft.com_yumrepos_azurecore_.gpgcheck=0",
            sudo=True,
            force_run=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "fail to set opts "
                "packages.microsoft.com_yumrepos_azurecore_.gpgcheck=0"
            ),
        )

    def test_add_repository_skips_gpgcheck_when_gpgcheck_enabled(self) -> None:
        tool = self._create_tool()
        with patch.object(YumConfigManager, "run") as mock_run:
            tool.add_repository(
                "https://packages.microsoft.com/yumrepos/azurecore/",
                no_gpgcheck=False,
            )

        cmd = tool.node.execute.call_args.kwargs["cmd"]
        self.assertNotIn("--nogpgcheck", cmd)
        mock_run.assert_not_called()

    def test_add_repository_skips_repo_file_urls(self) -> None:
        tool = self._create_tool()
        with patch.object(YumConfigManager, "run") as mock_run:
            tool.add_repository("https://example.com/custom.repo")

        mock_run.assert_not_called()
