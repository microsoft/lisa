# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

from lisa.executable import Tool
from lisa.operating_system import CBLMariner, Debian, Redhat
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
        elif isinstance(node.os, Redhat):
            return GrubConfigRedhat(node, args, kwargs)

        raise UnsupportedDistroException(
            os=node.os,
            message="Grub tool only supported on CBLMariner 2.0/3.0, "
            "Debian-based distributions, and RHEL-based distributions.",
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

    def _remove_existing_arg(self, arg: str, grub_file: str, line_regex: str) -> None:
        from lisa.tools import Sed

        self.node.tools[Sed].delete_line_substring(
            match_line=line_regex,
            regex_to_delete=(r"\s" + arg + r"[^\"[:space:]]*"),
            file=PurePosixPath(grub_file),
            sudo=True,
        )

    def _add_new_arg(
        self, arg: str, value: str, grub_file: str, line_regex: str
    ) -> None:
        from lisa.tools import Sed

        self.node.tools[Sed].substitute(
            match_lines=line_regex,
            regexp='"$',
            replacement=f' {arg}={value}"',
            file=grub_file,
            sudo=True,
        )

    def _validate_grub_file_exists(self, grub_file: str) -> None:
        if not self.node.shell.exists(PurePosixPath(grub_file)):
            raise LisaException(f"GRUB configuration file {grub_file} not found")


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
        self._remove_existing_arg(
            arg, self._GRUB_DEFAULT_FILE, self._GRUB_CMDLINE_LINE_REGEX
        )
        self._add_new_arg(
            arg, value, self._GRUB_DEFAULT_FILE, self._GRUB_CMDLINE_LINE_REGEX
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
        self._validate_grub_file_exists(self._GRUB_DEFAULT_FILE)
        self._remove_existing_arg(
            arg, self._GRUB_DEFAULT_FILE, self._GRUB_CMDLINE_LINUX_REGEX
        )
        self._add_new_arg(
            arg, value, self._GRUB_DEFAULT_FILE, self._GRUB_CMDLINE_LINUX_REGEX
        )

        # Apply the changes using update-grub
        self.run(
            "",
            sudo=True,
            force_run=True,
            expected_exit_code=0,
        )


class GrubConfigRedhat(GrubConfig):
    _GRUB_CMDLINE_LINE_REGEX = r"^GRUB_CMDLINE_LINUX="
    _GRUB_DEFAULT_FILE = "/etc/default/grub"

    def __init__(self, node: "Node", *args: Any, **kwargs: Any) -> None:
        super().__init__("grub2-mkconfig", "grub2-tools", node, *args, **kwargs)

    def set_kernel_cmdline_arg(self, arg: str, value: str) -> None:
        # Check if BLS (Boot Loader Specification) is enabled
        if self._is_bls_enabled():
            self._log.info("BLS is enabled, using grubby to modify kernel parameters")
            self._set_kernel_arg_with_grubby(arg, value)
        else:
            self._log.info("BLS is not enabled, using grub2-mkconfig method")
            self._set_kernel_arg_with_grub2(arg, value)

    def _is_bls_enabled(self) -> bool:
        """
        Check if Boot Loader Specification (BLS) is enabled.
        BLS is the default in RHEL 9 and newer versions.
        """
        # Check if GRUB_ENABLE_BLSCFG=true in /etc/default/grub
        result = self.node.execute(
            "grep -q '^GRUB_ENABLE_BLSCFG=true' /etc/default/grub", sudo=True
        )
        if result.exit_code == 0:
            return True

        return False

    def _set_kernel_arg_with_grubby(self, arg: str, value: str) -> None:
        """
        Use grubby to set kernel parameters for BLS-enabled systems.
        This is the recommended method for RHEL 9+.
        """
        # First, check if grubby is installed
        grubby_check = self.node.execute("command -v grubby", sudo=True)
        if grubby_check.exit_code != 0:
            posix_os: Posix = self.node.os  # type: ignore
            posix_os.install_packages("grubby")

        # Use grubby to update kernel parameters for ALL kernels
        self.node.execute(
            f"grubby --update-kernel=ALL --args='{arg}={value}'",
            sudo=True,
            expected_exit_code=0,
        )
        self._log.info(f"Successfully added {arg}={value} using grubby")

    def _set_kernel_arg_with_grub2(self, arg: str, value: str) -> None:
        """
        Use grub2-mkconfig to set kernel parameters for non-BLS systems.
        """
        self._validate_grub_file_exists(self._GRUB_DEFAULT_FILE)
        self._remove_existing_arg(
            arg, self._GRUB_DEFAULT_FILE, self._GRUB_CMDLINE_LINE_REGEX
        )
        self._add_new_arg(
            arg, value, self._GRUB_DEFAULT_FILE, self._GRUB_CMDLINE_LINE_REGEX
        )

        # Determine correct GRUB config path (UEFI vs BIOS)
        grub_cfg_path = self._get_grub_config_path()
        self._log.info(f"Using GRUB config path: {grub_cfg_path}")

        # Apply the changes using grub2-mkconfig
        self.run(
            f"-o {grub_cfg_path}",
            sudo=True,
            force_run=True,
            expected_exit_code=0,
        )

    def _get_grub_config_path(self) -> str:
        """
        Determine the correct GRUB configuration file path.
        UEFI systems use /boot/efi/EFI/*/grub.cfg
        BIOS systems use /boot/grub2/grub.cfg
        """
        from lisa.tools import Ls

        ls_tool = self.node.tools[Ls]
        uefi_check = ls_tool.run("/sys/firmware/efi", sudo=True, force_run=True)
        if uefi_check.exit_code == 0:
            self._log.debug("Detected UEFI system, checking for UEFI GRUB paths")

            # UEFI system - check common UEFI paths
            uefi_paths = [
                "/boot/efi/EFI/redhat/grub.cfg",
                "/boot/efi/EFI/centos/grub.cfg",
                "/boot/efi/EFI/almalinux/grub.cfg",
                "/boot/efi/EFI/rocky/grub.cfg",
                "/boot/efi/EFI/BOOT/grub.cfg",
            ]

            for path in uefi_paths:
                ls_result = ls_tool.run(path, sudo=True, force_run=True)
                if ls_result.exit_code == 0:
                    self._log.debug(f"Found UEFI GRUB config at: {path}")
                    return path

            # Fallback: try to find any grub.cfg in EFI directory
            self._log.debug("Trying fallback: search for grub.cfg in EFI directory")
            result = self.node.execute(
                "find /boot/efi/EFI -name grub.cfg 2>/dev/null | head -1", sudo=True
            )
            if result.stdout.strip():
                found_path = result.stdout.strip()
                self._log.debug(f"Found GRUB config via fallback: {found_path}")
                return found_path

        # Default to BIOS path
        self._log.debug("Using default BIOS GRUB config path")
        return "/boot/grub2/grub.cfg"
