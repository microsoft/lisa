# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from pathlib import PurePath
from typing import Optional, Type, Any
from lisa.node import Node
from lisa.sut_orchestrator.azure.common import (
    add_user_assign_identity,
    get_node_context,
    create_user_assign_identity,
    delete_user_assign_identity,
)
from lisa.executable import Tool
from lisa.tools.powershell import PowerShell


class AzCopy(Tool):
    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        self._command: str = ""
        self.resource_group_name = get_node_context(self.node).resource_group_name
        self.location = get_node_context(self.node).location
        self.vm_name = get_node_context(self.node).vm_name
        self.msi = ""
        self._auth()

    @property
    def command(self) -> str:
        return "azcopy"

    @property
    def can_install(self) -> bool:
        return True

    def cleanup(self) -> None:
        delete_user_assign_identity("AzurePlatform", self.resource_group_name, self.node.log)

    def _auth(self) -> None:
        msi = create_user_assign_identity(
            resource_group_name=self.resource_group_name,
            location = self.location,
            self.node.log,
        )
        # Assign the user assigned managed identity to the VM
        add_user_assign_identity(
            "AzurePlatform", self.resource_group_name, self.vm_name, msi.id, self.node.log
        )
        self.node.log.info(f"{self.msi} is assigned to {self.vm_name} successfully")

        # set the environment variables
        self.node.tools[PowerShell].run_cmdlet(
            "azcopy login --identity",
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
