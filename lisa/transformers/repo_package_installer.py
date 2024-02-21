from dataclasses import dataclass, field
from typing import Any, Dict, List, Type

from dataclasses_json import dataclass_json

from lisa import schema
from lisa.operating_system import Posix
from lisa.transformers.deployment_transformer import (
    DeploymentTransformer,
    DeploymentTransformerSchema,
)


@dataclass_json()
@dataclass
class RepoPackageInstallerTransformerSchema(DeploymentTransformerSchema):
    install_packages: List[str] = field(default_factory=list)


class RepoPackageInstallerTransformer(DeploymentTransformer):
    """
    This Transformer installs packages from a repository.
    """

    @classmethod
    def type_name(cls) -> str:
        return "install_repo_packages"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return RepoPackageInstallerTransformerSchema

    @property
    def _output_names(self) -> List[str]:
        return []

    def _internal_run(self) -> Dict[str, Any]:
        runbook: RepoPackageInstallerTransformerSchema = self.runbook
        assert isinstance(runbook, RepoPackageInstallerTransformerSchema)
        node = self._node

        # Only Posix has install_packages method
        if not isinstance(node.os, Posix):
            raise NotImplementedError(
                "RepoPackageInstallerTransformer is not "
                f"supported on {node.os.__class__.__name__}"
            )

        if runbook.install_packages and any(runbook.install_packages):
            node.os.install_packages(runbook.install_packages)
        else:
            self._log.debug(
                "No packages are specified in the runbook, nothing to install."
            )

        return {}
