import random
import string
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, List, Type

from lisa import feature, schema
from lisa.environment import Environment
from lisa.node import Node, RemoteNode
from lisa.platform_ import Platform
from lisa.tools import HyperV, PowerShell
from lisa.util.logger import Logger, get_logger

from .. import HYPERV
from .context import NodeContext
from .features import SerialConsole, StartStop
from .schema import HypervNodeSchema, HypervPlatformSchema


class HypervPlatform(Platform):
    def __init__(
        self,
        runbook: schema.Platform,
    ) -> None:
        super().__init__(runbook=runbook)

    @classmethod
    def type_name(cls) -> str:
        return HYPERV

    @classmethod
    def supported_features(cls) -> List[Type[feature.Feature]]:
        return [StartStop, SerialConsole]

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        hyperv_runbook = self.runbook.get_extended_runbook(HypervPlatformSchema)
        assert hyperv_runbook, "platform runbook cannot be empty"
        self._hyperv_runbook = hyperv_runbook
        print("Hyperv platform initialize")
        print(f"{self._hyperv_runbook}")

        if len(self._hyperv_runbook.servers) > 1:
            self._log.warning(
                "Multiple servers are currently not supported. "
                "Only the server host will be used."
            )

        server = self._hyperv_runbook.servers[0]
        self.server_node = RemoteNode(
            runbook=schema.Node(name="hyperv-server"),
            index=-1,
            logger_name="hyperv-server",
            parent_logger=get_logger("hyperv-platform"),
        )
        self.server_node.set_connection_info(
            address=server.address, username=server.username, password=server.password
        )

    def _prepare_environment(self, environment: Environment, log: Logger) -> bool:
        print("hyperv platform prepare environment")
        print(f"{environment.runbook}")
        return True

    def _deploy_environment(self, environment: Environment, log: Logger) -> None:
        print(self.server_node.tools[PowerShell].run_cmdlet("Get-VM"))
        # print(self.server_node.working_path)
        self._deploy_nodes(environment, log)

    def _get_node_context(self, node: Node) -> NodeContext:
        return node.get_context(NodeContext)

    def _deploy_nodes(self, environment: Environment, log: Logger) -> None:
        print("hyperv platform deploy nodes")

        test_suffix = "".join(random.choice(string.ascii_uppercase) for _ in range(5))
        vm_name_prefix = f"lisa-{test_suffix}"

        hv = self.server_node.tools[HyperV]
        pwsh = self.server_node.tools[PowerShell]
        default_switch = hv.get_first_switch()

        for i, node_space in enumerate(environment.runbook.nodes_requirement):
            node_runbook = node_space.get_extended_runbook(
                HypervNodeSchema, type(self).type_name()
            )

            vm_name = f"{vm_name_prefix}-{i}"

            print(f"{i} {node_runbook} {node_space.core_count} {node_space.memory_mb}")

            node = environment.create_node_from_requirement(node_space)
            assert isinstance(node, RemoteNode)

            node_context = self._get_node_context(node)
            node_context.vm_name = f"{vm_name_prefix}-{i}"
            node_context.vhd_local_path = PurePosixPath(node_runbook.vhd)
            node_context.vhd_remote_path = PureWindowsPath(
                f"C:/Users/Administrator/lisa_test/{vm_name}-vhd.vhdx"
            )

            remote_path = node_context.vhd_remote_path
            is_zipped = False
            if node_context.vhd_local_path.suffix == ".zip":
                remote_path = PureWindowsPath(
                    f"C:/Users/Administrator/lisa_test/{vm_name}-vhd.zip"
                )
                is_zipped = True

            self.server_node.shell.copy(node_context.vhd_local_path, remote_path)
            if is_zipped:
                extraction_path = remote_path.parent.joinpath("extracted")
                self.server_node.tools[PowerShell].run_cmdlet(
                    f"Expand-Archive -Path {remote_path} -DestinationPath {extraction_path} -Force"
                )
                extracted_vhd = self.server_node.tools[PowerShell].run_cmdlet(
                    f"Get-ChildItem -Path {extraction_path} | Select -First 1 -ExpandProperty Name"
                )
                extracted_vhd = extraction_path.joinpath(extracted_vhd)
                pwsh.run_cmdlet(
                    f"Copy-Item -Path {extracted_vhd} -Destination {node_context.vhd_remote_path}"
                )
                self.server_node.shell.remove(remote_path)

            hv.create_vm(
                name=vm_name,
                guest_image_path=node_context.vhd_remote_path,
                switch_name=default_switch,
                generation=node_runbook.hyperv_generation,
                cores=node.capability.core_count,
                memory=node.capability.memory_mb,
                secure_boot=False,
            )

            ip_addr = hv.get_ip_address(vm_name)
            username = self.runbook.admin_username
            password = self.runbook.admin_password
            node.set_connection_info(
                address=ip_addr, username=username, password=password
            )
