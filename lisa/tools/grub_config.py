# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

from lisa.executable import Tool
from lisa.operating_system import CBLMariner
from lisa.tools import Sed
from lisa.util import UnsupportedDistroException

if TYPE_CHECKING:
    from lisa.node import Node
    from lisa.operating_system import Posix


class GrubConfig(Tool):
    @classmethod
    def create(cls, node: "Node", *args: Any, **kwargs: Any) -> Tool:
        """
        Factory method to create an instance of the Grub tool.
        """
        if isinstance(node.os, CBLMariner):
            if node.os.information.release == "2.0":
                return GrubConfigAzl2(node, args, kwargs)
            if node.os.information.release == "3.0":
                return GrubConfigAzl3(node, args, kwargs)

        raise UnsupportedDistroException(
            os=node.os, message="Grub tool only supported on CBLMariner 2.0 and 3.0."
        )

    def __init__(
        self, command: str, package: str, node: "Node", *args: Any, **kwargs: Any
    ) -> None:
        super().__init__(node, *args, **kwargs)
        self._command = command
        self._package = package

    @property
    def command(self) -> str:
        return self._command

    @property
    def can_install(self) -> bool:
        return True

    def set_fips_mode(self, fips_mode: bool) -> None:
        """
        Set the FIPS mode to the specified value.
        """
        raise NotImplementedError("set_fips_mode is not implemented.")

    def set_boot_uuid(self, uuid: str, same_as_root: bool) -> None:
        """
        Set the boot UUID to the specified value.
        """
        if same_as_root:
            self.remove_kernel_cmdline_arg(r"boot")
        else:
            self.set_kernel_cmdline_arg(f"boot=UUID={uuid}")

    def unset_boot_uuid(self, same_as_root: bool) -> None:
        """
        Unset the boot UUID.
        """
        raise NotImplementedError("unset_boot_uuid is not implemented.")

    def remove_kernel_cmdline_arg(self, arg: str) -> None:
        """
        Remove the specified kernel command line argument from the grub configuration.
        """
        raise NotImplementedError("remove_kernel_cmdline_arg is not implemented.")

    def set_kernel_cmdline_arg(self, arg: str) -> None:
        """
        Append the specified kernel command line argument to the grub configuration.
        """
        raise NotImplementedError("set_kernel_cmdline_arg is not implemented.")

    def _install(self) -> bool:
        posix_os: Posix = self.node.os  # type: ignore
        posix_os.install_packages(self._package)
        return self._check_exists()


class GrubConfigAzl2(GrubConfig):
    def __init__(self, node: "Node", *args: Any, **kwargs: Any) -> None:
        super().__init__("grubby", "grubby", node, *args, **kwargs)

    def set_fips_mode(self, fips_mode: bool) -> None:
        fips_flag = "fips=1" if fips_mode else "fips=0"
        self.set_kernel_cmdline_arg(fips_flag)

    def unset_boot_uuid(self, same_as_root: bool) -> None:
        if same_as_root:
            self.remove_kernel_cmdline_arg(r"boot")
        else:
            self.set_kernel_cmdline_arg("boot=")

    def remove_kernel_cmdline_arg(self, arg: str) -> None:
        self._run(f"--remove-args='{arg}'")

    def set_kernel_cmdline_arg(self, arg: str) -> None:
        self._run(f"--args='{arg}'")

    def _run(self, added_arg: str) -> None:
        """
        Call grubby to update the kernel command line arguments.
        """
        self.run(
            f"--update-kernel=ALL {added_arg}",
            sudo=True,
            force_run=True,
            expected_exit_code=0,
        )


class GrubConfigAzl3(GrubConfig):
    _GRUB_CMDLINE_LINE_REGEX = r"^GRUB_CMDLINE_LINUX="
    _GRUB_DEFAULT_FILE = "/etc/default/grub"

    def __init__(self, node: "Node", *args: Any, **kwargs: Any) -> None:
        super().__init__("grub2-mkconfig", "grub2-tools-minimal", node, *args, **kwargs)

    def set_fips_mode(self, fips_mode: bool) -> None:
        self.remove_kernel_cmdline_arg("fips")
        if fips_mode:
            self.set_kernel_cmdline_arg("fips=1")

    def unset_boot_uuid(self, same_as_root: bool) -> None:
        self.remove_kernel_cmdline_arg(r"boot")

    def remove_kernel_cmdline_arg(self, arg: str) -> None:
        self.node.tools[Sed].delete_line_substring(
            match_line=self._GRUB_CMDLINE_LINE_REGEX,
            regex_to_delete=(r"\s" + arg + r"[^\"\s]*"),
            file=PurePosixPath(self._GRUB_DEFAULT_FILE),
            sudo=True,
        )
        self._apply()

    def set_kernel_cmdline_arg(self, arg: str) -> None:
        """
        Append the specified kernel command line argument to the grub configuration.
        """
        self.node.tools[Sed].substitute(
            match_lines=self._GRUB_CMDLINE_LINE_REGEX,
            regexp='"$',
            replacement=f' {arg}"',
            file=self._GRUB_DEFAULT_FILE,
            sudo=True,
        )
        self._apply()

    def _apply(self) -> None:
        """
        Reconfigure grub to apply the changes made to the kernel command line arguments.
        """
        self.run(
            "--output=/boot/grub2/grub.cfg",
            sudo=True,
            force_run=True,
            expected_exit_code=0,
        )
