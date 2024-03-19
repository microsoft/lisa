# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from dataclasses import dataclass, field
from pathlib import PurePath
from typing import Any, Dict, List, Type

from dataclasses_json import dataclass_json

from lisa import schema
from lisa.operating_system import RPMDistro
from lisa.tools import Rpm
from lisa.transformers.deployment_transformer import (
    DeploymentTransformer,
    DeploymentTransformerSchema,
)
from lisa.util import UnsupportedDistroException, field_metadata


@dataclass_json()
@dataclass
class PackageInstallerSchema(DeploymentTransformerSchema):
    # Node's local absolute path of directory where package files are located
    directory: str = field(default="", metadata=field_metadata(required=True))
    # list of package files to be installed
    files: List[str] = field(default_factory=list)
    # reboot after installation
    reboot: bool = field(default=False)


class PackageInstaller(DeploymentTransformer):
    @classmethod
    def type_name(cls) -> str:
        return "package_installer"

    def _validate_package(self, file: str) -> None:
        raise NotImplementedError()

    def _install_package(self, file: str) -> None:
        raise NotImplementedError()

    def _validate(self) -> None:
        runbook: PackageInstallerSchema = self.runbook
        directory: PurePath = PurePath(runbook.directory)
        for file in runbook.files:
            assert self._node.shell.exists(
                directory / file
            ), f"Node does not contain package file: {file}"
            self._validate_package(str(directory / file))

    def _internal_run(self) -> Dict[str, Any]:
        runbook: PackageInstallerSchema = self.runbook

        self._log.info(f"Installing packages: {runbook.files}")
        directory: PurePath = PurePath(runbook.directory)
        for file in runbook.files:
            self._install_package(self._node.get_str_path(directory.joinpath(file)))

        if runbook.reboot:
            self._node.reboot(time_out=900)

        return {}


class RPMPackageInstallerTransformer(PackageInstaller):
    @classmethod
    def type_name(cls) -> str:
        return "rpm_package_installer"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return PackageInstallerSchema

    @property
    def _output_names(self) -> List[str]:
        return []

    def _validate(self) -> None:
        if not isinstance(self._node.os, RPMDistro):
            raise UnsupportedDistroException(
                self._node.os,
                f"'{self.type_name()}' transformer only supports RPM based Distros.",
            )
        super()._validate()

    def _validate_package(self, file: str) -> None:
        assert self._node.tools[Rpm].is_valid_package(
            file
        ), f"Provided file {file} is not an rpm"

    def _install_package(self, file: str) -> None:
        self._node.tools[Rpm].install_local_package(file, force=True, nodeps=True)
