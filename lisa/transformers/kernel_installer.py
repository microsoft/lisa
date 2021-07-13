# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.


import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Type, cast

from dataclasses_json import CatchAll, Undefined, dataclass_json

from lisa import schema
from lisa.node import Node, quick_connect
from lisa.operating_system import Ubuntu
from lisa.secret import PATTERN_HEADTAIL, add_secret
from lisa.tools import Cat, Uname
from lisa.transformer import Transformer
from lisa.util import filter_ansi_escape, get_matched_str, subclasses
from lisa.util.logger import Logger, get_logger


@dataclass_json(undefined=Undefined.INCLUDE)
@dataclass
class BaseInstallerSchema(schema.TypedSchema):
    delay_parsed: CatchAll = field(default_factory=dict)  # type: ignore


@dataclass_json()
@dataclass
class RepoInstallerSchema(BaseInstallerSchema):
    # the source of repo. It uses to specify a uncommon source in repo.
    # examples: linux-azure, linux-azure-edge, linux-image-azure-lts-20.04,
    # linux-image-4.18.0-1025-azure
    source: str = field(
        default="proposed",
        metadata=schema.metadata(
            required=True,
        ),
    )

    # some repo has the proposed versions, it uses to specify if it should be
    # retrieve from proposed.
    is_proposed: bool = True


@dataclass_json()
@dataclass
class PpaInstallerSchema(RepoInstallerSchema):
    # The OpenPGP key of the PPA repo
    openpgp_key: str = ""
    # The URL of PPA url, and it may need to include credential.
    ppa_url: str = field(
        default="",
        metadata=schema.metadata(
            required=True,
        ),
    )
    # The PPA repo doesn't have proposed kernels by default
    is_proposed: bool = False

    def __post_init__(self, *args: Any, **kwargs: Any) -> None:
        add_secret(self.ppa_url, PATTERN_HEADTAIL)


@dataclass_json
@dataclass
class KernelInstallerTransformerSchema(schema.Transformer):
    # the SSH connection information to the node
    connection: Optional[schema.RemoteNode] = field(
        default=None, metadata=schema.metadata(required=True)
    )
    # the installer's paramerters.
    installer: Optional[BaseInstallerSchema] = field(
        default=None, metadata=schema.metadata(required=True)
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
        self._log = get_logger("kernel_installer", parent=parent_log)

    def validate(self) -> None:
        raise NotImplementedError()

    def install(self) -> None:
        raise NotImplementedError()


class KernelInstallerTransformer(Transformer):
    @classmethod
    def type_name(cls) -> str:
        return "kernel_installer"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return KernelInstallerTransformerSchema

    @property
    def _output_names(self) -> List[str]:
        return []

    def _internal_run(self) -> Dict[str, Any]:
        runbook: KernelInstallerTransformerSchema = self.runbook
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
        installer.install()

        self._log.info("rebooting")
        node.reboot()
        self._log.info(
            f"kernel version after install: "
            f"{uname.get_linux_information(force_run=True)}"
        )

        return {}


class RepoInstaller(BaseInstaller):
    # gnulinux-5.11.0-1011-azure-advanced-3fdd2548-1430-450b-b16d-9191404598fb
    # prefix: gnulinux
    # postfix: advanced-3fdd2548-1430-450b-b16d-9191404598fb
    __menu_id_parts_pattern = re.compile(
        r"^(?P<prefix>.*?)-.*-(?P<postfix>.*?-.*?-.*?-.*?-.*?-.*?)?$"
    )

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
        return "repo"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return RepoInstallerSchema

    def validate(self) -> None:
        assert isinstance(self._node.os, Ubuntu), (
            f"The '{self.type_name()}' installer only support Ubuntu. "
            f"The current os is {self._node.os.__class__.__name__}"
        )

    def install(self) -> None:
        runbook: RepoInstallerSchema = self.runbook
        node: Node = self._node
        ubuntu: Ubuntu = cast(Ubuntu, node.os)
        release = node.os.os_version.codename

        assert (
            release
        ), f"cannot find codename from the os version: {node.os.os_version}"

        # add the repo
        if runbook.is_proposed:
            version_name = f"{release}-proposed"
        else:
            version_name = release
        repo_entry = (
            f"deb {self.repo_url} {version_name} "
            f"restricted main multiverse universe"
        )
        ubuntu.wait_running_package_process()
        result = node.execute(f'add-apt-repository "{repo_entry}"', sudo=True)
        if result.exit_code != 0:
            result.assert_exit_code(
                message="failed on add repo\n"
                + "\n".join(ubuntu.get_apt_error(result.stdout))
            )

        full_package_name = f"{runbook.source}/{version_name}"
        self._log.info(f"installing kernel package: {full_package_name}")
        ubuntu.install_packages(full_package_name)

        kernel_version = self._get_kernel_version(runbook.source, node)

        self._replace_boot_entry(kernel_version, node)

        # install tool packages
        ubuntu.install_packages(
            [
                f"linux-tools-{kernel_version}-azure",
                f"linux-cloud-tools-{kernel_version}-azure",
                f"linux-headers-{kernel_version}-azure",
            ]
        )

    def _get_kernel_version(self, source: str, node: Node) -> str:
        # get kernel version from apt packages
        # linux-azure-edge/focal-proposed,now 5.11.0.1011.11~20.04.10 amd64 [installed]
        # output: 5.11.0.1011
        # linux-image-4.18.0-1025-azure/bionic-updates,bionic-security,now
        # 4.18.0-1025.27~18.04.1 amd64 [installed]
        # output 4.18.0-1025
        kernel_version_package_pattern = re.compile(
            f"^{source}/[^ ]+ "
            r"(?P<kernel_version>[^.]+\.[^.]+\.[^.-]+[.-][^.]+)\..*[\r\n]+",
            re.M,
        )
        result = node.execute(f"apt search {source}", shell=True)
        result_output = filter_ansi_escape(result.stdout)
        kernel_version = get_matched_str(result_output, kernel_version_package_pattern)
        assert kernel_version, (
            f"cannot find kernel version from apt results by pattern: "
            f"{kernel_version_package_pattern.pattern}"
        )
        self._log.info(f"installed kernel version: {kernel_version}")

        return kernel_version

    def _replace_boot_entry(self, kernel_version: str, node: Node) -> None:
        self._log.info("updating boot menu...")
        ubuntu: Ubuntu = cast(Ubuntu, node.os)

        # set installed kernel to default
        #
        # get boot entry id
        # postive example:
        #         menuentry 'Ubuntu, with Linux 5.11.0-1011-azure' --class ubuntu
        # --class gnu-linux --class gnu --class os $menuentry_id_option
        # 'gnulinux-5.11.0-1011-azure-advanced-3fdd2548-1430-450b-b16d-9191404598fb' {
        #
        # negative example:
        #         menuentry 'Ubuntu, with Linux 5.11.0-1011-azure (recovery mode)'
        # --class ubuntu --class gnu-linux --class gnu --class os $menuentry_id_option
        # 'gnulinux-5.11.0-1011-azure-recovery-3fdd2548-1430-450b-b16d-9191404598fb' {
        cat = node.tools[Cat]
        menu_id_pattern = re.compile(
            r"^.*?menuentry '.*?(?:"
            + kernel_version
            + r"[^ ]*?)(?<! \(recovery mode\))' "
            r".*?\$menuentry_id_option .*?'(?P<menu_id>.*)'.*$",
            re.M,
        )
        result = cat.run("/boot/grub/grub.cfg")
        submenu_id = get_matched_str(result.stdout, menu_id_pattern)
        assert submenu_id, (
            f"cannot find sub menu id from grub config by pattern: "
            f"{menu_id_pattern.pattern}"
        )
        self._log.debug(f"matched submenu_id: {submenu_id}")

        # get first level menu id in boot menu
        # input is the sub menu id like:
        # gnulinux-5.11.0-1011-azure-advanced-3fdd2548-1430-450b-b16d-9191404598fb
        # output is,
        # gnulinux-advanced-3fdd2548-1430-450b-b16d-9191404598fb
        menu_id = self.__menu_id_parts_pattern.sub(
            r"\g<prefix>-\g<postfix>", submenu_id
        )
        assert menu_id, f"cannot composite menu id from {submenu_id}"

        # composite boot menu in grub
        menu_entry = f"{menu_id}>{submenu_id}"
        self._log.debug(f"composited menu_entry: {menu_entry}")

        ubuntu.set_boot_entry(menu_entry)
        node.execute("update-grub", sudo=True)


class PpaInstaller(RepoInstaller):
    @classmethod
    def type_name(cls) -> str:
        return "ppa"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return PpaInstallerSchema

    def install(self) -> None:
        runbook: PpaInstallerSchema = self.runbook
        node: Node = self._node

        # the key is optional
        if runbook.openpgp_key:
            result = node.execute(
                f"apt-key adv --keyserver keyserver.ubuntu.com --recv-keys "
                f"{runbook.openpgp_key}",
                sudo=True,
            )
            result.assert_exit_code(message="error on import key")

        # replace default repo url
        self.repo_url = runbook.ppa_url

        super().install()
