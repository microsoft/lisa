# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

from lisa.executable import Tool
from lisa.operating_system import CBLMariner, Debian
from lisa.tools import Sed
from lisa.util import LisaException, UnsupportedDistroException

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
        elif isinstance(node.os, Debian):
            return GrubConfigDebian(node, args, kwargs)

        raise UnsupportedDistroException(
            os=node.os,
            message="Grub tool only supported on CBLMariner 2.0/3.0 and "
            "Debian-based distributions.",
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

    def set_kernel_cmdline_arg(self, arg: str, value: str) -> None:
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

    def set_kernel_cmdline_arg(self, arg: str, value: str) -> None:
        self._run(f"--args='{arg}={value}'")

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

    def set_kernel_cmdline_arg(self, arg: str, value: str) -> None:
        """
        Append the specified kernel command line argument to the grub configuration.
        """
        # For simplicity, first remove the existing argument.
        self.node.tools[Sed].delete_line_substring(
            match_line=self._GRUB_CMDLINE_LINE_REGEX,
            regex_to_delete=(r"\s" + arg + r"[^\"[:space:]]*"),
            file=PurePosixPath(self._GRUB_DEFAULT_FILE),
            sudo=True,
        )

        # Add the new argument.
        self.node.tools[Sed].substitute(
            match_lines=self._GRUB_CMDLINE_LINE_REGEX,
            regexp='"$',
            replacement=f' {arg}={value}"',
            file=self._GRUB_DEFAULT_FILE,
            sudo=True,
        )

        # Apply the changes.
        self.run(
            "--output=/boot/grub2/grub.cfg",
            sudo=True,
            force_run=True,
            expected_exit_code=0,
        )


class GrubConfigDebian(GrubConfig):
    _GRUB_CMDLINE_LINUX_REGEX = r"^GRUB_CMDLINE_LINUX="
    _GRUB_DEFAULT_FILE = "/etc/default/grub"

    def __init__(self, node: "Node", *args: Any, **kwargs: Any) -> None:
        super().__init__("update-grub", "grub-common", node, *args, **kwargs)

    def set_kernel_cmdline_arg(self, arg: str, value: str) -> None:
        """
        Append the specified kernel command line argument to GRUB_CMDLINE_LINUX
        for Debian-based systems.
        """
        if not self.node.shell.exists(PurePosixPath(self._GRUB_DEFAULT_FILE)):
            raise LisaException(
                f"GRUB configuration file {self._GRUB_DEFAULT_FILE} not found"
            )

        # For simplicity, first remove the existing argument if present.
        self.node.tools[Sed].delete_line_substring(
            match_line=self._GRUB_CMDLINE_LINUX_REGEX,
            regex_to_delete=(r"\s" + arg + r"[^\"[:space:]]*"),
            file=PurePosixPath(self._GRUB_DEFAULT_FILE),
            sudo=True,
        )

        self.node.tools[Sed].substitute(
            match_lines=self._GRUB_CMDLINE_LINUX_REGEX,
            regexp='"$',
            replacement=f' {arg}={value}"',
            file=self._GRUB_DEFAULT_FILE,
            sudo=True,
        )

        self.run(
            "",
            sudo=True,
            force_run=True,
            expected_exit_code=0,
        )
