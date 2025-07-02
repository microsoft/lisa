# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from dataclasses import dataclass, field
from pathlib import PurePath
from typing import Type

from dataclasses_json import dataclass_json

from lisa import schema
from lisa.operating_system import CBLMariner, RPMDistro
from lisa.tools import Rpm
from lisa.util import UnsupportedDistroException, field_metadata

from .kernel_installer import BaseInstaller, BaseInstallerSchema


@dataclass_json()
@dataclass
class RPMInstallerSchema(BaseInstallerSchema):
    # kernel rpm - Node's local absolute path
    kernel_rpm_path: str = field(
        default="",
        metadata=field_metadata(
            required=True,
        ),
    )


class RPMInstaller(BaseInstaller):
    @classmethod
    def type_name(cls) -> str:
        return "rpm"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return RPMInstallerSchema

    def validate(self) -> None:
        if not isinstance(self._node.os, RPMDistro):
            raise UnsupportedDistroException(
                self._node.os,
                f"The '{self.type_name()}' installer only support RPM based Distros. ",
            )
        runbook: RPMInstallerSchema = self.runbook
        kernel_rpm_path: str = runbook.kernel_rpm_path
        assert self._node.shell.exists(
            PurePath(kernel_rpm_path)
        ), f"Node does not contain kernel rpm file: {kernel_rpm_path}"
        assert self._node.tools[Rpm].is_valid_package(
            kernel_rpm_path
        ), f"Provided file {kernel_rpm_path} is not an rpm"

    def install(self) -> str:
        node = self._node
        runbook: RPMInstallerSchema = self.runbook
        kernel_rpm_path: str = runbook.kernel_rpm_path

        rpm = node.tools[Rpm]
        rpm.install_local_package(kernel_rpm_path, force=True, nodeps=True)
        filename = PurePath(kernel_rpm_path).name
        installed_kernel_version = filename[: -len(".rpm")]

        # Always configure newly installed kernel as default boot option
        if isinstance(node.os, CBLMariner):
            self._configure_installed_kernel_boot(node, installed_kernel_version)

        return installed_kernel_version


    def _configure_installed_kernel_boot(self, node, kernel_version: str) -> None:
        """Configure newly installed kernel as default boot option using grubby."""
        try:
            # Extract the actual kernel version from the RPM name
            # Examples:
            # kernel-lvbs-6.6.89-9.cm2.x86_64 -> 6.6.89-9.cm2
            # kernel-5.15.185.1-2.cm2.x86_64 -> 5.15.185.1-2.cm2
            if kernel_version.startswith("kernel-lvbs-"):
                actual_version = kernel_version.replace("kernel-lvbs-", "").rsplit(".", 1)[0]
            elif kernel_version.startswith("kernel-"):
                actual_version = kernel_version.replace("kernel-", "").rsplit(".", 1)[0]
            else:
                actual_version = kernel_version
            
            # First, let's see what kernels grubby can find
            available_kernels = node.execute(
                "grubby --info=ALL | grep '^kernel=' | cut -d= -f2",
                sudo=True,
                shell=True,
            )
            self._log.info(f"Available kernels found by grubby: {available_kernels.stdout}")
            
            # Construct the expected kernel path
            kernel_path = f"/boot/vmlinuz-{actual_version}"
            
            # Check if the kernel file exists
            kernel_check = node.execute(
                f"ls -la {kernel_path}",
                sudo=True,
                expected_exit_code=[0, 2],  # Allow file not found
            )
            
            if kernel_check.exit_code != 0:
                self._log.warning(f"Kernel file {kernel_path} not found, searching for alternatives...")
                # Try to find the kernel by pattern
                kernel_search = node.execute(
                    f"ls -la /boot/vmlinuz-*{actual_version}*",
                    sudo=True,
                    shell=True,
                    expected_exit_code=[0, 2],
                )
                if kernel_search.exit_code == 0:
                    # Extract the first found kernel
                    found_kernels = kernel_search.stdout.strip().split('\n')
                    if found_kernels:
                        # Get the kernel path from the ls output
                        kernel_path = found_kernels[0].split()[-1]
                        self._log.info(f"Found alternative kernel path: {kernel_path}")
            
            # Try to set the kernel as default
            result = node.execute(
                f"grubby --set-default={kernel_path}",
                sudo=True,
                expected_exit_code=[0, 1],  # Allow failure for further handling
            )
            
            if result.exit_code == 0:
                self._log.info(f"Successfully set installed kernel {kernel_path} as default boot entry")
            else:
                # If direct path fails, try using grubby's kernel discovery
                self._log.warning(f"Direct path failed, trying alternative approach: {result.stdout}")
                
                # List all kernels and find the one matching our version
                info_result = node.execute(
                    "grubby --info=ALL",
                    sudo=True,
                )
                
                # Look for our kernel version in the output
                if actual_version in info_result.stdout:
                    self._log.info(f"Found kernel {actual_version} in grubby info, attempting index-based setting")
                    # Try setting by index (newest kernel is usually index 0)
                    index_result = node.execute(
                        "grubby --set-default-index=0",
                        sudo=True,
                        expected_exit_code=[0, 1],
                    )
                    if index_result.exit_code == 0:
                        self._log.info("Successfully set kernel as default using index 0")
                    else:
                        self._log.warning(f"Index-based setting also failed: {index_result.stdout}")
                else:
                    self._log.warning(f"Kernel version {actual_version} not found in grubby info")
            
        except Exception as e:
            self._log.warning(f"Failed to configure kernel boot order: {e}")
            # Don't fail the installation, just log the warning
