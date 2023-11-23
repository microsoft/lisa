# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from dataclasses import dataclass, field
from pathlib import PurePath
from typing import Type

from dataclasses_json import dataclass_json

from lisa import schema
from lisa.operating_system import RPMDistro
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

        return installed_kernel_version
