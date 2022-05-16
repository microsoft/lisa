# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import cast

from lisa.executable import Tool
from lisa.operating_system import CBLMariner, Linux, Ubuntu
from lisa.util import LisaException


class QemuImg(Tool):
    @property
    def command(self) -> str:
        return "qemu-img"

    @property
    def can_install(self) -> bool:
        for _os in [CBLMariner, Ubuntu]:
            if isinstance(self.node.os, _os):
                return True
        return False

    def _install(self) -> bool:
        linux: Linux = cast(Linux, self.node.os)
        if isinstance(self.node.os, CBLMariner):
            linux.install_packages("qemu-img")
        elif isinstance(self.node.os, CBLMariner):
            linux.install_packages("qemu-utils")
        else:
            raise LisaException("Missing QemuImg tool install impl for {linux} os")
        return self._check_exists()

    def create_new_qcow2(self, output_img_path: str, size_mib: int) -> None:
        self.run(
            f'create -f qcow2 "{output_img_path}" {size_mib}M',
            force_run=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="Failed to create disk image.",
        )

    def create_diff_qcow2(self, output_img_path: str, backing_img_path: str) -> None:
        params = f'create -F qcow2 -f qcow2 -b "{backing_img_path}" "{output_img_path}"'
        self.run(
            params,
            force_run=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="Failed to create differential disk.",
        )

    def convert(
        self, src_format: str, src_path: str, dest_format: str, dest_path: str
    ) -> None:
        self.run(
            f"convert -f {src_format} -O {dest_format} {src_path} {dest_path}",
            force_run=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="Failed to convert disk image",
        )
