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
            
            # Use grubby to set the newly installed kernel as default
            kernel_path = f"/boot/vmlinuz-{actual_version}"
            
            # Set the installed kernel as default boot entry
            result = node.execute(
                f"grubby --set-default={kernel_path}",
                sudo=True,
                expected_exit_code=0,
            )
            
            self._log.info(f"Set installed kernel {kernel_path} as default boot entry")
            
        except Exception as e:
            self._log.warning(f"Failed to configure kernel boot order: {e}")
            # Don't fail the installation, just log the warning
