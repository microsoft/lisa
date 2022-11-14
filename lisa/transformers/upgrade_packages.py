from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Type

from dataclasses_json import dataclass_json

from lisa import schema
from lisa.node import Node, quick_connect
from lisa.operating_system import Debian
from lisa.tools import Uname
from lisa.transformer import Transformer
from lisa.util import field_metadata, subclasses
from lisa.util.logger import Logger, get_logger


@dataclass_json()
@dataclass
class BaseInstallerSchema(schema.TypedSchema, schema.ExtendableSchemaMixin):
    ...


@dataclass_json
@dataclass
class UpgradeInstallerTransformerSchema(schema.Transformer):
    # SSH connection information to the node
    connection: Optional[schema.RemoteNode] = field(
        default=None, metadata=field_metadata(required=True)
    )
    # installer's parameters.
    installer: Optional[BaseInstallerSchema] = field(
        default=None, metadata=field_metadata(required=True)
    )


class BaseInstaller(subclasses.BaseClassWithRunbookMixin):
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

    def install(self) -> str:
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
        factory = subclasses.Factory[BaseInstaller](BaseInstaller)
        installer = factory.create_by_runbook(
            runbook=runbook.installer, node=node, parent_log=self._log
        )

        installer.validate()
        package_list = installer.install()
        self._log.info(f"Packages upgraded: {package_list}")

        self._log.info("rebooting")
        node.reboot()
        self._log.info(
            f"kernel version after install: "
            f"{uname.get_linux_information(force_run=True)}"
        )

        return {}


class UnattendedUpgradeInstaller(BaseInstaller):
    def __init__(
        self,
        runbook: Any,
        node: Node,
        parent_log: Logger,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(runbook, node, parent_log, *args, **kwargs)
        self.repo_url = "http://archive.ubuntu.com/ubuntu/"

    @classmethod
    def type_name(cls) -> str:
        return "unattended_upgrade"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return BaseInstallerSchema

    def validate(self) -> None:
        assert isinstance(self._node.os, Debian), (
            f"The '{self.type_name()}' installer only supports Debian family. "
            f"The current os is {self._node.os.name}"
        )

    def install(self) -> str:
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

        return result.stdout
