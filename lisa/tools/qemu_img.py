# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from lisa.executable import Tool


class QemuImg(Tool):
    @property
    def command(self) -> str:
        return "qemu-img"

    def create_diff_qcow2(self, output_img_path: str, backing_img_path: str) -> None:
        params = f"create -F qcow2 -f qcow2 -b {backing_img_path} {output_img_path}"
        self.run(params, True)
