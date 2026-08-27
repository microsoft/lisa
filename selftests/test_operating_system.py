import shlex
from typing import Tuple
from unittest import TestCase
from unittest.mock import MagicMock

from assertpy import assert_that

from lisa.base_tools import Cat, Sed
from lisa.operating_system import CBLMariner


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
