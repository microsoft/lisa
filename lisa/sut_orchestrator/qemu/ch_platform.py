# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import List, Type

import libvirt  # type: ignore

from lisa.environment import Environment
from lisa.feature import Feature
from lisa.node import Node
from lisa.sut_orchestrator.qemu.context import NodeContext, get_node_context
from lisa.sut_orchestrator.qemu.platform import BaseLibvirtPlatform
from lisa.tools import QemuImg
from lisa.util.logger import Logger

from .. import CLOUD_HYPERVISOR
from .schema import DiskImageFormat


class CloudHypervisorPlatform(BaseLibvirtPlatform):
    @classmethod
    def type_name(cls) -> str:
        return CLOUD_HYPERVISOR

    @classmethod
    def supported_features(cls) -> List[Type[Feature]]:
        return BaseLibvirtPlatform._supported_features

    def _libvirt_uri_schema(self) -> str:
        return "ch"

    def _create_node_domain_xml(
        self, environment: Environment, log: Logger, node: Node
    ) -> str:
        node_context = get_node_context(node)

        # TODO (anrayabh): generate domain xml
        with open("/home/anirudh/dom_ch_template.xml", "r") as f:
            dom_ch = f.read()
        dom_ch = dom_ch.replace("{domain_name}", node_context.vm_name)
        dom_ch = dom_ch.replace(
            "{cloud_init_iso_path}", node_context.cloud_init_file_path
        )
        dom_ch = dom_ch.replace("{os_disk_file_path}", node_context.os_disk_file_path)
        return dom_ch

    def _stop_and_delete_vm(
        self,
        environment: Environment,
        log: Logger,
        qemu_conn: libvirt.virConnect,
        node: Node,
    ) -> None:
        super()._stop_and_delete_vm_flags(
            environment,
            log,
            qemu_conn,
            node,
            0,  # ch driver currently doesn't support any flags
        )

    def _create_domain_and_attach_logger(
        self,
        libvirt_conn: libvirt.virConnect,
        domain: libvirt.virDomain,
        node_context: NodeContext,
    ) -> None:
        domain.createWithFlags(0)

        assert node_context.console_logger
        node_context.console_logger.attach(
            libvirt_conn, domain, node_context.console_log_file_path
        )

    # Create the OS disk.
    def _create_node_os_disk(
        self, environment: Environment, log: Logger, node: Node
    ) -> None:
        node_context = get_node_context(node)
        if node_context.os_disk_base_file_fmt == DiskImageFormat.QCOW2:
            self.host_node.tools[QemuImg].convert(
                "qcow2",
                node_context.os_disk_base_file_path,
                "raw",
                node_context.os_disk_file_path,
            )
        else:
            self.host_node.execute(
                f"cp {node_context.os_disk_base_file_path}"
                f" {node_context.os_disk_file_path}",
                expected_exit_code=0,
                expected_exit_code_failure_message="Failed to copy os disk image",
            )
