# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import os
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
    # kernel rpm - local absolute path
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
        err: str = f"can not find kernel rpm file: {kernel_rpm_path}"
        assert os.path.exists(kernel_rpm_path), err
        assert kernel_rpm_path.endswith(
            ".rpm"
        ), f"Provided file {kernel_rpm_path} is not an rpm"

    def install(self) -> str:
        node = self._node
        runbook: RPMInstallerSchema = self.runbook
        kernel_rpm_path: str = runbook.kernel_rpm_path

        filename = os.path.basename(kernel_rpm_path)
        remote_path = node.working_path / filename
        node.shell.copy(
            PurePath(kernel_rpm_path),
            remote_path,
        )

        rpm = node.tools[Rpm]
        rpm.install_local_package(str(remote_path))
        installed_kernel_version = filename[: -len(".rpm")]

        return installed_kernel_version
