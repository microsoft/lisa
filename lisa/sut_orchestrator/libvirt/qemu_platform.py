# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from typing import List, Type

from lisa.environment import Environment
from lisa.feature import Feature
from lisa.node import Node
from lisa.sut_orchestrator.libvirt.context import get_node_context
from lisa.sut_orchestrator.libvirt.platform import BaseLibvirtPlatform
from lisa.tools import QemuImg
from lisa.util.logger import Logger, filter_ansi_escape

from .. import QEMU
from .schema import QemuNodeSchema

QEMU_VERSION_PATTERN = re.compile(r"QEMU emulator version (?P<qemu_version>.+)\s")


class QemuPlatform(BaseLibvirtPlatform):
    @classmethod
    def type_name(cls) -> str:
        return QEMU

    @classmethod
    def supported_features(cls) -> List[Type[Feature]]:
        return BaseLibvirtPlatform._supported_features

    @classmethod
    def node_runbook_type(cls) -> type:
        return QemuNodeSchema

    def _libvirt_uri_schema(self) -> str:
        return "qemu"

    # Create the OS disk.
    def _create_node_os_disk(
        self, environment: Environment, log: Logger, node: Node
    ) -> None:
        node_context = get_node_context(node)
        self.host_node.tools[QemuImg].create_diff_qcow2(
            node_context.os_disk_file_path, node_context.os_disk_base_file_path
        )
        if node_context.os_disk_img_resize_gib:
            self.host_node.tools[QemuImg].resize(
                src_file=node_context.os_disk_file_path,
                size_gib=node_context.os_disk_img_resize_gib,
            )

    def _get_vmm_version(self) -> str:
        result = "Unknown"
        if self.host_node:
            output = self.host_node.execute(
                "qemu-system-x86_64 --version",
                shell=True,
            ).stdout
            output = filter_ansi_escape(output)
            match = re.search(QEMU_VERSION_PATTERN, output.strip())
            if match:
                result = match.group("qemu_version")
        return result
