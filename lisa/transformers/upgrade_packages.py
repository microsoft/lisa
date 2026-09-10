from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Type

from dataclasses_json import dataclass_json

from lisa import schema
from lisa.node import Node
from lisa.operating_system import Debian, Ubuntu
from lisa.tools import Sed, Uname
from lisa.transformers.deployment_transformer import (
    DeploymentTransformer,
    DeploymentTransformerSchema,
)
from lisa.util import field_metadata, subclasses
from lisa.util.logger import Logger, get_logger


@dataclass_json()
@dataclass
class UpgradeInstallerSchema(schema.TypedSchema, schema.ExtendableSchemaMixin):
    repo_url: str = field(default="")

    proposed: bool = field(default=False)


@dataclass_json
@dataclass
class UpgradeTransformerSchema(DeploymentTransformerSchema):
    installer: Optional[UpgradeInstallerSchema] = field(
        default=None, metadata=field_metadata(required=True)
    )


class UpgradeInstaller(subclasses.BaseClassWithRunbookMixin):
    def __init__(
        self,
        runbook: Any,
        node: Node,
        parent_log: Logger,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(runbook, *args, **kwargs)
        self._node = node
        self._log = get_logger("upgrade_installer", parent=parent_log)

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return UpgradeInstallerSchema

    def validate(self) -> None:
        raise NotImplementedError()

    def install(self) -> List[str]:
        raise NotImplementedError()


class UpgradeTransformer(DeploymentTransformer):
    @classmethod
    def type_name(cls) -> str:
        return "upgrade"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return UpgradeTransformerSchema

    @property
    def _output_names(self) -> List[str]:
        return []

    def _internal_run(self) -> Dict[str, Any]:
        runbook: UpgradeTransformerSchema = self.runbook
        assert runbook.installer, "installer must be defined."

        node = self._node

        uname = node.tools[Uname]
        self._log.info(
            f"kernel version before install: {uname.get_linux_information()}"
        )
        factory = subclasses.Factory[UpgradeInstaller](UpgradeInstaller)

        installer = factory.create_by_runbook(
            runbook=runbook.installer, node=node, parent_log=self._log
        )
        installer.validate()
        installer.install()

        return {}


class UnattendedUpgradeInstaller(UpgradeInstaller):
    def __init__(
        self,
        runbook: Any,
        node: Node,
        parent_log: Logger,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(runbook, node, parent_log, *args, **kwargs)

    @classmethod
    def type_name(cls) -> str:
        return "unattended_upgrade"

    def validate(self) -> None:
        assert isinstance(self._node.os, Debian), (
            f"The '{self.type_name()}' installer only supports Debian family. "
            f"The current os is {self._node.os.name}"
        )

    def install(self) -> List[str]:
        if self.runbook.repo_url.strip():
            self._update_repo()

        return self._update_packages()

    def _update_repo(self) -> None:
        node: Node = self._node
        runbook: UpgradeInstallerSchema = self.runbook
        repo_url = runbook.repo_url
        assert isinstance(node.os, Ubuntu)
        release = node.os.information.codename

        assert (
            release
        ), f"cannot find codename from the os version: {node.os.information}"

        sed = node.tools[Sed]
        sed.run(
            f"-E '/{release} main/!s/(.*)/#\\1/' -i /etc/apt/sources.list",
            shell=True,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="fail to comment out other repo sources",
        )

        if runbook.proposed:
            version_name = f"{release}-proposed"
        else:
            version_name = release

        repo_entry = (
            f"deb {repo_url} {version_name} " f"restricted main multiverse universe"
        )
        node.os.add_repository(repo_entry)

    def _update_packages(self) -> List[str]:
        node: Node = self._node
        assert isinstance(node.os, Debian)

        # Make sure unattended-upgrade is installed
        cmd_result = node.execute(
            "which unattended-upgrade",
            sudo=True,
            shell=True,
        )
        if 0 != cmd_result.exit_code:
            node.os.install_packages("unattended-upgrades")
        if type(node.os) is Debian:
            if node.os.information.version >= "10.0.0":
                node.execute(
                    "mkdir -p /var/cache/apt/archives/partial",
                    sudo=True,
                    shell=True,
                    expected_exit_code=0,
                    expected_exit_code_failure_message=(
                        "fail to make folder /var/cache/apt/archives/partial"
                    ),
                )
            else:
                node.os.install_packages(["debian-keyring", "debian-archive-keyring"])

        node.execute(
            "apt update",
            sudo=True,
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="fail to run apt-update",
        )
        result = node.execute(
            "apt list --upgradable | awk '{printf(\"%s %s\\n\",$1,$2)}'",
            sudo=True,
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="fail to get upgrade-package list",
        )
        upgradable_before = [package.strip() for package in result.stdout.split("\n")]

        node.os.wait_running_package_process()
        node.execute(
            "unattended-upgrade -d -v",
            sudo=True,
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="fail to run unattended-upgrade",
            timeout=2400,
        )

        result = node.execute(
            "apt list --upgradable | awk '{printf(\"%s %s\\n\",$1,$2)}'",
            sudo=True,
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="fail to get upgrade-package list",
        )
        upgradable_after = [package.strip() for package in result.stdout.split("\n")]

        # Return a list packages that were upgraded
        return [
            package for package in upgradable_before if package not in upgradable_after
        ]


class FullUpgradeInstaller(UpgradeInstaller):
    def __init__(
        self,
        runbook: Any,
        node: Node,
        parent_log: Logger,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(runbook, node, parent_log, *args, **kwargs)

    @classmethod
    def type_name(cls) -> str:
        return "full_upgrade"

    def validate(self) -> None:
        assert isinstance(self._node.os, Debian), (
            f"The '{self.type_name()}' installer only supports Debian family. "
            f"The current os is {self._node.os.name}"
        )

    def install(self) -> List[str]:
        if self.runbook.repo_url.strip():
            self._update_repo()

        return self._update_packages()

    def _update_repo(self) -> None:
        node: Node = self._node
        runbook: UpgradeInstallerSchema = self.runbook
        repo_url = runbook.repo_url
        assert isinstance(node.os, Ubuntu)
        release = node.os.information.codename

        assert (
            release
        ), f"cannot find codename from the os version: {node.os.information}"

        if runbook.proposed:
            version_name = f"{release}-proposed"
        else:
            version_name = release

        repo_entry = (
            f"deb {repo_url} {version_name} restricted main multiverse universe"
        )
        node.os.add_repository(repo_entry)

    def _update_packages(self) -> List[str]:
        node: Node = self._node
        assert isinstance(node.os, Debian)

        node.os.wait_running_package_process()
        node.execute(
            "apt update",
            sudo=True,
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="fail to run apt-update",
        )
        result = node.execute(
            "apt list --upgradable | awk '{printf(\"%s %s\\n\",$1,$2)}'",
            sudo=True,
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="fail to get upgrade-package list",
        )
        upgradable_before = [package.strip() for package in result.stdout.split("\n")]

        node.os.update_packages("--with-new-pkgs")

        result = node.execute(
            "apt list --upgradable | awk '{printf(\"%s %s\\n\",$1,$2)}'",
            sudo=True,
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="fail to get upgrade-package list",
        )
        upgradable_after = [package.strip() for package in result.stdout.split("\n")]

        # Return a list packages that were upgraded
        return [
            package for package in upgradable_before if package not in upgradable_after
        ]
