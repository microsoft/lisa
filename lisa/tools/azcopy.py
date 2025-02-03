# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from pathlib import PurePath
from typing import Optional, Type, Any
from lisa.node import NodeContext, Node
from lisa.util import add_user_assign_identity

from lisa.executable import Tool
from lisa.tools.powershell import PowerShell


class AzCopy(Tool):
    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        self._command: str = ""
        self._auth()

    @property
    def command(self) -> str:
        return "azcopy"

    @property
    def can_install(self) -> bool:
        return True

    def _auth(
        self,
        blob_url: str,
        local_file_path: PurePath,
        sudo: bool = False,
        timeout: int = 600,
    ) -> None:
        msi_client = self._get_managed_service_identity_client()
        node_context = self._get_node_context(self.node)
        resource_group_name = node_context.resource_group_name
        location = node_context.location
        vm_name = node_context.vm_name
        # Create a user assigned managed identity
        msi_name = f"{resource_group_name}-msi"
        msi = msi_client.user_assigned_identities.create_or_update(
            resource_group_name=resource_group_name,
            resource_name=msi_name,
            parameters={"location": location},
        )
        self.node.log.info(f"{msi.id} is created successfully")
        # Assign the user assigned managed identity to the VM
        add_user_assign_identity("AzurePlatform", resource_group_name, vm_name, msi.id, self.node.log)
        self.node.log.info(f"{msi.id} is assigned to {vm_name} successfully")

        # set the environment variables
        self.node.tools[PowerShell].run_cmdlet(
            'azcopy login --identity',
            sudo=True,
            fail_on_error=True,
        )

    def download_file(
        self,
        blob_url: str,
        local_file_path: PurePath,
        sudo: bool = False,
        timeout: int = 600,
    ) -> None:
        raise NotImplementedError()

    def upload_file(
        self,
        blob_url: str,
        local_file_path: PurePath,
        sudo: bool = False,
        timeout: int = 600,
    ) -> None:
        raise NotImplementedError()

    @classmethod
    def _windows_tool(cls) -> Optional[Type[Tool]]:
        return WindowsAzCopy

    def _get_node_context(self, node: Node) -> NodeContext:
        return node.get_context(NodeContext)


class WindowsAzCopy(AzCopy):
    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        self._command: str = ""

    @property
    def command(self) -> str:
        return self._command

    def download_file(
        self,
        blob_url: str,
        local_file_path: PurePath,
        sudo: bool = False,
        timeout: int = 600,
    ) -> None:
        self._azcopy_file(
            source=blob_url,
            destination=str(local_file_path),
            sudo=sudo,
            timeout=timeout,
        )

    def upload_file(
        self,
        blob_url: str,
        local_file_path: PurePath,
        sudo: bool = False,
        timeout: int = 600,
    ) -> None:
        self._azcopy_file(
            destination=blob_url,
            source=str(local_file_path),
            sudo=sudo,
            timeout=timeout,
        )

    def _azcopy_file(
        self,
        source: str,
        destination: str,
        sudo: bool = False,
        timeout: int = 600,
    ) -> None:
        cmd = f'{self.command} copy "{source}" "{destination}"'
        self.node.tools[PowerShell].run_cmdlet(
            cmd, sudo=sudo, timeout=timeout, fail_on_error=True
        )

    def _check_exists(self) -> bool:
        return False

    def _install(self) -> bool:
        download_path = r"C:\AzCopy.zip"
        install_path = r"C:\AzCopy"
        ps = self.node.tools[PowerShell]
        # download azcopy
        ps.run_cmdlet(
            f'Invoke-WebRequest -Uri "https://aka.ms/downloadazcopy-v10-windows" '
            f'-OutFile "{download_path}"',
            sudo=True,
            fail_on_error=True,
        )
        # extract azcopy
        ps.run_cmdlet(
            f'Expand-Archive -Path "{download_path}" -DestinationPath "{install_path}"',
            sudo=True,
            fail_on_error=True,
        )
        # get the path of azcopy.exe
        self._command = ps.run_cmdlet(
            f"(Get-ChildItem -path '{install_path}'"
            " -Recurse -File -Filter 'azcopy.exe').FullName",
            sudo=True,
            fail_on_error=True,
            output_json=True,
        )

        return True
