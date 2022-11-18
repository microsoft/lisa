from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Type

from dataclasses_json import dataclass_json

from lisa import schema
from lisa.node import Node, quick_connect
from lisa.operating_system import Debian, Ubuntu
from lisa.tools import Uname
from lisa.transformer import Transformer
from lisa.util import field_metadata, subclasses
from lisa.util.logger import Logger, get_logger


@dataclass_json()
@dataclass
class UpgradeInstallerSchema(schema.TypedSchema, schema.ExtendableSchemaMixin):
    ...


@dataclass_json
@dataclass
class UpgradeInstallerTransformerSchema(schema.Transformer):
    # SSH connection information to the node
    connection: Optional[schema.RemoteNode] = field(
        default=None, metadata=field_metadata(required=True)
    )
    repo_updater: Optional[UpgradeInstallerSchema] = field(
        default=None, metadata=field_metadata(required=False)
    )
    # installer's parameters.
    installer: Optional[UpgradeInstallerSchema] = field(
        default=None, metadata=field_metadata(required=False)
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

    def validate(self) -> None:
        raise NotImplementedError()

    def install(self) -> None:
        raise NotImplementedError()


class UpgradeInstallerTransformer(Transformer):
    @classmethod
    def type_name(cls) -> str:
        return "upgrade_installer"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return UpgradeInstallerTransformerSchema

    @property
    def _output_names(self) -> List[str]:
        return []

    def _internal_run(self) -> Dict[str, Any]:
        runbook: UpgradeInstallerTransformerSchema = self.runbook
        assert runbook.connection, "connection must be defined."
        assert runbook.installer, "installer must be defined."

        node = quick_connect(runbook.connection, "installer_node")

        uname = node.tools[Uname]
        self._log.info(
            f"kernel version before install: {uname.get_linux_information()}"
        )
        factory = subclasses.Factory[UpgradeInstaller](UpgradeInstaller)
        if runbook.repo_updater:
            repo_updater = factory.create_by_runbook(
                runbook=runbook.repo_updater, node=node, parent_log=self._log
            )
            repo_updater.validate()
            repo_updater.install()

        if runbook.installer:
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

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return UpgradeInstallerSchema

    def validate(self) -> None:
        assert isinstance(self._node.os, Debian), (
            f"The '{self.type_name()}' installer only supports Debian family. "
            f"The current os is {self._node.os.name}"
        )

    def install(self) -> None:
        node: Node = self._node
        assert isinstance(node.os, Debian)

        cmd_result = node.execute(
            "which unattended-upgrade",
            sudo=True,
            shell=True,
        )
        if 0 != cmd_result.exit_code:
            node.os.install_packages("unattended-upgrades")
        if type(node.os) == Debian:
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
            "apt list --upgradable",
            sudo=True,
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="fail to get upgrade-package list",
        )
        node.execute(
            "unattended-upgrade -d -v",
            sudo=True,
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="fail to run unattended-upgrade",
            timeout=2400,
        )

        self._log.debug(f"Packages updated: {result.stdout}")


class AddProposedRepoInstaller(UpgradeInstaller):
    def __init__(
        self,
        runbook: Any,
        node: Node,
        parent_log: Logger,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(runbook, node, parent_log, *args, **kwargs)
        self.repo_url = "http://azure.archive.ubuntu.com/ubuntu/"

    @classmethod
    def type_name(cls) -> str:
        return "add_proposed_repo"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return UpgradeInstallerSchema

    def validate(self) -> None:
        assert isinstance(self._node.os, Ubuntu), (
            f"The '{self.type_name()}' installer only supports Ubuntu family. "
            f"The current os is {self._node.os.name}"
        )

    def install(self) -> None:
        node: Node = self._node
        assert isinstance(node.os, Ubuntu)
        release = node.os.information.codename

        assert (
            release
        ), f"cannot find codename from the os version: {node.os.information}"

        version_name = f"{release}-proposed"

        repo_entry = (
            f"deb {self.repo_url} {version_name} "
            f"restricted main multiverse universe"
        )
        node.os.add_repository(repo_entry)
