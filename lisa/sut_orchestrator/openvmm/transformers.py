# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Type, cast

from dataclasses_json import dataclass_json

from lisa import schema
from lisa.transformers.deployment_transformer import (
    DeploymentTransformer,
    DeploymentTransformerSchema,
)
from lisa.util import field_metadata, subclasses

from .installer import OpenVmmInstaller
from .schema import OpenVmmInstallerSchema


@dataclass_json()
@dataclass
class OpenVmmInstallerTransformerSchema(DeploymentTransformerSchema):
    installer: Optional[OpenVmmInstallerSchema] = field(
        default=None, metadata=field_metadata(required=True)
    )


class OpenVmmInstallerTransformer(DeploymentTransformer):
    @classmethod
    def type_name(cls) -> str:
        return "openvmm_installer"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return OpenVmmInstallerTransformerSchema

    @property
    def _output_names(self) -> List[str]:
        return []

    def _internal_run(self) -> Dict[str, Any]:
        runbook = cast(OpenVmmInstallerTransformerSchema, self.runbook)
        assert runbook.installer, "installer must be defined"
        installer_runbook = schema.load_by_type(OpenVmmInstallerSchema, runbook.installer)

        installer_factory = subclasses.Factory[OpenVmmInstaller](OpenVmmInstaller)
        installer = installer_factory.create_by_runbook(
            runbook=installer_runbook,
            node=self._node,
            log=self._log,
        )
        force_install = getattr(installer_runbook, "force_install", False)
        install_path = getattr(installer_runbook, "install_path", "openvmm")
        self._log.info(
            f"checking OpenVMM on node '{self._node.name}' with "
            f"install_path='{install_path}', force_install={force_install}"
        )

        try:
            version = installer._run_version_command()
            is_installed = True
        except Exception:
            version = ""
            is_installed = False

        if not is_installed or force_install:
            installer.validate()
            version = installer.install()
            self._log.info(
                f"installed OpenVMM version: {version} to '{install_path}'"
            )
        else:
            self._log.info(
                f"OpenVMM already available on PATH. Version: {version}"
            )

        verified_version = installer._run_version_command(install_path)
        self._log.info(
            f"verified OpenVMM at '{install_path}'. Version: {verified_version}"
        )

        try:
            path_version = installer._run_version_command()
            self._log.info(f"verified OpenVMM on PATH. Version: {path_version}")
        except Exception as identifier_error:
            self._log.warning(
                "OpenVMM is not available on PATH after transformer execution: "
                f"{identifier_error}"
            )

        return {}
