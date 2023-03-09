# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.


import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Type, cast

from dataclasses_json import dataclass_json

from lisa import schema
from lisa.node import Node, quick_connect
from lisa.operating_system import Posix, Ubuntu
from lisa.secret import PATTERN_HEADTAIL, add_secret
from lisa.tools import Uname
from lisa.transformer import Transformer
from lisa.util import field_metadata, filter_ansi_escape, get_matched_str, subclasses
from lisa.util.logger import Logger, get_logger


@dataclass_json()
@dataclass
class BaseInstallerSchema(schema.TypedSchema, schema.ExtendableSchemaMixin):
    ...


@dataclass_json()
@dataclass
class RepoInstallerSchema(BaseInstallerSchema):
    # the source of repo. It uses to specify a uncommon source in repo.
    # examples: linux-azure, linux-azure-edge, linux-image-azure-lts-20.04,
    # linux-image-4.18.0-1025-azure
    source: str = field(
        default="proposed",
        metadata=field_metadata(
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
        metadata=field_metadata(
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
        default=None, metadata=field_metadata(required=True)
    )
    # the installer's parameters.
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
        self._log = get_logger("kernel_installer", parent=parent_log)

    @property
    def information(self) -> Dict[str, Any]:
        return dict()

    def validate(self) -> None:
        raise NotImplementedError()

    def install(self) -> str:
        raise NotImplementedError()


class KernelInstallerTransformer(Transformer):
    _information_output_name = "information"
    _information: Dict[str, Any] = dict()

    @classmethod
    def type_name(cls) -> str:
        return "kernel_installer"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return KernelInstallerTransformerSchema

    @property
    def _output_names(self) -> List[str]:
        return [self._information_output_name]

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
        installed_kernel_version = installer.install()
        self._information = installer.information
        self._log.info(f"installed kernel version: {installed_kernel_version}")

        # for ubuntu cvm kernel, there is no menuentry added into grub file
        if hasattr(installer.runbook, "source"):
            if installer.runbook.source != "linux-image-azure-fde":
                posix = cast(Posix, node.os)
                posix.replace_boot_kernel(installed_kernel_version)
            else:
                efi_files = node.execute(
                    "ls -t /usr/lib/linux/efi/kernel.efi-*-azure-cvm",
                    sudo=True,
                    shell=True,
                    expected_exit_code=0,
                    expected_exit_code_failure_message=(
                        "fail to find kernel.efi file for kernel type "
                        " linux-image-azure-fde"
                    ),
                )
                efi_file = efi_files.stdout.splitlines()[0]
                node.execute(
                    (
                        "cp /boot/efi/EFI/ubuntu/grubx64.efi "
                        "/boot/efi/EFI/ubuntu/grubx64.efi.bak"
                    ),
                    sudo=True,
                )
                node.execute(
                    f"cp {efi_file} /boot/efi/EFI/ubuntu/grubx64.efi",
                    sudo=True,
                    shell=True,
                )

        self._log.info("rebooting")
        node.reboot()
        self._log.info(
            f"kernel version after install: "
            f"{uname.get_linux_information(force_run=True)}"
        )
        return {self._information_output_name: self._information}


class RepoInstaller(BaseInstaller):
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
            f"The current os is {self._node.os.name}"
        )

    def install(self) -> str:
        runbook: RepoInstallerSchema = self.runbook
        node: Node = self._node
        ubuntu: Ubuntu = cast(Ubuntu, node.os)
        release = node.os.information.codename
        repo_component = "restricted main multiverse universe"

        assert (
            release
        ), f"cannot find codename from the os version: {node.os.information}"

        # add the repo
        # 'main' is the only repo component supported by 'private-ppa' and
        # 'proposed2' repositories
        if runbook.is_proposed:
            if "proposed2" in self.repo_url or "private-ppa" in self.repo_url:
                version_name = release
                repo_component = "main"
            else:
                version_name = f"{release}-proposed"
        else:
            version_name = release
        repo_entry = f"deb {self.repo_url} {version_name} {repo_component}"
        self._log.info(f"Adding repository: {repo_entry}")
        ubuntu.add_repository(repo_entry)
        full_package_name = f"{runbook.source}/{version_name}"
        self._log.info(f"installing kernel package: {full_package_name}")
        ubuntu.install_packages(full_package_name)

        kernel_version = self._get_kernel_version(runbook.source, node)

        return kernel_version

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


class PpaInstaller(RepoInstaller):
    @classmethod
    def type_name(cls) -> str:
        return "ppa"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return PpaInstallerSchema

    def install(self) -> str:
        runbook: PpaInstallerSchema = self.runbook
        node: Node = self._node

        # the key is optional
        if runbook.openpgp_key:
            node.execute(
                f"apt-key adv --keyserver keyserver.ubuntu.com --recv-keys "
                f"{runbook.openpgp_key}",
                sudo=True,
                expected_exit_code=0,
                expected_exit_code_failure_message="error on import key",
            )

        # replace default repo url
        self.repo_url = runbook.ppa_url

        return super().install()
