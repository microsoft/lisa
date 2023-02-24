# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, Dict, List, Optional, Type

from dataclasses_json import dataclass_json

from lisa import LisaException, schema
from lisa.node import quick_connect
from lisa.operating_system import Debian, Oracle, Redhat
from lisa.tools import Cat, Sed, Uname
from lisa.transformer import Transformer
from lisa.util import field_metadata


@dataclass_json()
@dataclass
class BootParametersTransformerSchema(schema.Transformer):
    # the SSH connection information to the node
    connection: Optional[schema.RemoteNode] = field(
        default=None, metadata=field_metadata(required=True)
    )
    parameters: List[str] = field(default_factory=list)


class BootParametersTransformer(Transformer):
    @classmethod
    def type_name(cls) -> str:
        return "boot_parameters"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return BootParametersTransformerSchema

    @property
    def _output_names(self) -> List[str]:
        return []

    def _internal_run(self) -> Dict[str, Any]:
        runbook: BootParametersTransformerSchema = self.runbook
        assert runbook.connection, "connection must be defined."
        assert len(runbook.parameters) > 0, "at least one parameter must e defined."

        cmd_line_append: str = " ".join(runbook.parameters)
        node = quick_connect(runbook.connection, "boot_parameters_node")

        node.tools[Sed].substitute(
            regexp='GRUB_CMDLINE_LINUX="\\(.*\\)"',
            replacement=f'GRUB_CMDLINE_LINUX="\\1 {cmd_line_append}"',
            file="/etc/default/grub",
            sudo=True,
        )
        if isinstance(node.os, Debian):
            node.execute("update-grub", sudo=True)
        elif isinstance(node.os, Redhat):
            if node.os.information.version >= "8.0.0-0" and not isinstance(
                node.os, Oracle
            ):
                kernel_ver_raw = (
                    node.tools[Uname].get_linux_information().kernel_version_raw
                )
                result = node.execute(
                    (
                        f'grubby --update-kernel="/boot/vmlinuz-{kernel_ver_raw}"'
                        f' --args="{cmd_line_append}"'
                    ),
                    sudo=True,
                )
                result.assert_exit_code(message="Failed to run grubby")
            else:
                arch = node.os.get_kernel_information().hardware_platform
                if (
                    node.shell.exists(PurePosixPath("/sys/firmware/efi"))
                    and arch == "x86_64"
                ):
                    # System with UEFI firmware
                    grub_file_path = node.execute(
                        "find /boot/efi/EFI/* -name grub.cfg", shell=True, sudo=True
                    )
                    result = node.execute(
                        f"grub2-mkconfig -o {grub_file_path}", sudo=True
                    )
                    result.assert_exit_code(message="Failed to run grub2-mkconfig")
                else:
                    # System with BIOS firmware Or ARM64 CentOS 7
                    result = node.execute(
                        "grub2-mkconfig -o /boot/grub2/grub.cfg", sudo=True
                    )
                    result.assert_exit_code(message="Failed to run grub2-mkconfig")

        node.reboot()

        cat = node.tools[Cat]
        cmdline = cat.read("/proc/cmdline")
        self._log.info(f"kernel cmdline: {cmdline}")
        self._log.info(f"searching for: '{cmd_line_append}'")
        if cmd_line_append in cmdline:
            return {}
        raise LisaException(
            "Appended boot parameters not found on kernel command line after boot"
        )
