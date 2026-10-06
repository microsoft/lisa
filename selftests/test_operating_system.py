import shlex
from pathlib import PurePosixPath
from typing import Any, Tuple
from unittest import TestCase
from unittest.mock import MagicMock

from assertpy import assert_that

from lisa.base_tools import Cat, Sed
from lisa.operating_system import CBLMariner
from lisa.tools import GrubConfig, Wget, YumConfigManager


class OperatingSystemTestCase(TestCase):
    def _create_mariner(
        self, grub_default_exists: bool
    ) -> Tuple[CBLMariner, MagicMock]:
        node = MagicMock()
        node.execute.return_value.exit_code = 0 if grub_default_exists else 1
        mariner = CBLMariner.__new__(CBLMariner)
        mariner._node = node
        mariner._log = MagicMock()
        return mariner, node

    def _create_mariner_for_replace_boot_kernel(
        self,
    ) -> Tuple[CBLMariner, MagicMock]:
        node = MagicMock()
        mariner = CBLMariner.__new__(CBLMariner)
        mariner._node = node
        mariner._log = MagicMock()
        return mariner, node

    def test_append_grub_default_on_new_line(self) -> None:
        mariner, node = self._create_mariner(grub_default_exists=False)
        entry = "AzureLinux GNU/Linux, with Linux 6.6.153.rc2-1.azl3"

        mariner._replace_default_entry(entry)

        grub_default_line = f"GRUB_DEFAULT={shlex.quote(entry)}"
        node.execute.assert_any_call(
            f"printf '\n%s\n' {shlex.quote(grub_default_line)} "
            "| sudo tee -a /etc/default/grub",
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="Failed to append GRUB_DEFAULT",
        )
        node.tools[Cat].run.assert_called_once_with("/etc/default/grub", sudo=True)

    def test_replace_existing_grub_default(self) -> None:
        mariner, node = self._create_mariner(grub_default_exists=True)
        entry = "AzureLinux GNU/Linux, with Linux 6.6.153.rc2-1.azl3"

        mariner._replace_default_entry(entry)

        node.tools[Sed].substitute.assert_called_once_with(
            regexp="GRUB_DEFAULT=.*",
            replacement=f"GRUB_DEFAULT={shlex.quote(entry)}",
            file="/etc/default/grub",
            sudo=True,
        )
        node.tools[Cat].run.assert_called_once_with("/etc/default/grub", sudo=True)

    def test_replace_boot_kernel_sets_securekernel_arg_for_lvbs(self) -> None:
        mariner, node = self._create_mariner_for_replace_boot_kernel()
        entry = "AzureLinux GNU/Linux, with Linux 6.6.135-lvbs-1.azl3"
        node.execute.return_value.stdout = f"menuentry '{entry}' {{"
        mariner._replace_default_entry = MagicMock()

        mariner.replace_boot_kernel("kernel-lvbs-6.6.135-1.azl3.x86_64")

        node.tools[GrubConfig].set_kernel_cmdline_arg.assert_called_once_with(
            "securekernel", "128M@0x8000000"
        )

    def test_replace_boot_kernel_skips_securekernel_arg_for_non_lvbs(self) -> None:
        mariner, node = self._create_mariner_for_replace_boot_kernel()
        entry = "AzureLinux GNU/Linux, with Linux 6.6.135-1.azl3"
        node.execute.return_value.stdout = f"menuentry '{entry}' {{"
        mariner._replace_default_entry = MagicMock()

        mariner.replace_boot_kernel("kernel-6.6.135-1.azl3.x86_64")

        node.tools[GrubConfig].set_kernel_cmdline_arg.assert_not_called()

    def test_get_kernel_version_candidates_for_standard_kernel(self) -> None:
        candidates = CBLMariner._get_kernel_version_candidates(
            "kernel-6.6.135-1.azl3.x86_64"
        )

        assert_that(candidates).is_equal_to(["6.6.135-1.azl3"])

    def test_get_kernel_version_candidates_for_flavored_kernel(self) -> None:
        candidates = CBLMariner._get_kernel_version_candidates(
            "kernel-lvbs-6.6.135-1.azl3.x86_64"
        )

        assert_that(candidates).is_equal_to(["6.6.135-1.azl3", "6.6.135-lvbs-1.azl3"])

    def test_get_kernel_version_candidates_for_unrecognized_name(self) -> None:
        candidates = CBLMariner._get_kernel_version_candidates("custom-kernel")

        assert_that(candidates).is_equal_to(["custom-kernel"])

    def test_cbl_mariner_add_repository_without_keys_location(self) -> None:
        mariner, node = self._create_mariner_for_replace_boot_kernel()

        mariner.add_repository("https://example.com/repo")

        node.tools[YumConfigManager].add_repository.assert_called_once_with(
            "https://example.com/repo", True
        )

    def test_cbl_mariner_add_repository_with_keys_location(self) -> None:
        mariner, node = self._create_mariner_for_replace_boot_kernel()
        working_path = PurePosixPath("/tmp/working")
        node.get_working_path.return_value = working_path

        key_url = "https://example.com/RPM-GPG-KEY-mariner"
        mariner.add_repository("https://example.com/repo", keys_location=[key_url])

        node.tools[Wget].get.assert_called_once_with(
            key_url,
            filename="RPM-GPG-KEY-mariner",
            save_path=working_path,
        )
        node.execute.assert_called_once_with(
            "rpm --import /tmp/working/RPM-GPG-KEY-mariner", sudo=True, shell=True
        )
        node.tools[YumConfigManager].add_repository.assert_called_once_with(
            "https://example.com/repo", False
        )
