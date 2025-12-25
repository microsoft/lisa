# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from dataclasses import dataclass, field
from pathlib import PurePath
from typing import Any, Dict, List, Type

from dataclasses_json import dataclass_json

from lisa import schema
from lisa.operating_system import RPMDistro
from lisa.tools import Rpm
from lisa.tools.ls import Ls
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
        node = self._node

        self._runbook_files: List[str] = runbook.files
        if self._runbook_files == ["*"]:
            self._runbook_files = []
            files = node.tools[Ls].list(str(directory))
            for file in files:
                self._runbook_files.append(PurePath(file).name)

        for file in self._runbook_files:
            assert self._node.shell.exists(
                directory / file
            ), f"Node does not contain package file: {file}"
            self._validate_package(str(directory / file))

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        super()._initialize(*args, **kwargs)
        runbook: PackageInstallerSchema = self.runbook
        if not runbook.directory:
            self._log.debug("no 'directory' provided.")
        if not runbook.files:
            self._log.debug("no 'files' to install.")

        self._validate()

    def _internal_run(self) -> Dict[str, Any]:
        runbook: PackageInstallerSchema = self.runbook
        uname = self._node.tools[Uname]
        installed_packages = []

        # Log kernel version before installation
        kernel_version = uname.get_linux_information().kernel_version_raw
        self._log.info(f"Kernel version before installation: {kernel_version}")

        self._log.info(f"Installing packages: {self._runbook_files}")
        directory: PurePath = PurePath(runbook.directory)
        for file in self._runbook_files:
            self._install_package(self._node.get_str_path(directory / file))
            installed_packages.append(file)

        self._log.info(f"Successfully installed: {installed_packages}")

        if runbook.reboot:
            self._node.reboot(time_out=900)
            kernel_version = uname.get_linux_information(
                force_run=True
            ).kernel_version_raw
            self._log.info(f"Kernel version after reboot: " f"{kernel_version}")

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
