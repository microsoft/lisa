# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import PurePath
from typing import Any, Dict, List, Optional, Type, cast

from dataclasses_json import dataclass_json

from lisa import schema
from lisa.base_tools import Mv
from lisa.node import Node
from lisa.operating_system import CBLMariner, Redhat, Ubuntu
from lisa.tools import Cp, Echo, Git, Make, Sed, Uname
from lisa.tools.gcc import Gcc
from lisa.tools.lscpu import Lscpu
from lisa.util import LisaException, field_metadata, subclasses
from lisa.util.logger import Logger, get_logger

from .kernel_installer import BaseInstaller, BaseInstallerSchema


@dataclass_json()
@dataclass
class BaseModifierSchema(schema.TypedSchema, schema.ExtendableSchemaMixin):
    ...


@dataclass_json()
@dataclass
class BaseLocationSchema(schema.TypedSchema, schema.ExtendableSchemaMixin):
    ...


@dataclass_json()
@dataclass
class LocalLocationSchema(BaseLocationSchema):
    path: str = field(
        default="",
        metadata=field_metadata(
            required=True,
        ),
    )


@dataclass_json()
@dataclass
class RepoLocationSchema(LocalLocationSchema):
    # source code repo
    repo: str = "https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git"
    ref: str = ""

    # fail the run if code exists
    fail_on_code_exists: bool = False
    cleanup_code: bool = False
    auth_token: Optional[str] = field(
        default=None,
        metadata=field_metadata(
            required=False,
        ),
    )


@dataclass_json()
@dataclass
class PatchModifierSchema(BaseModifierSchema):
    repo: str = field(
        default="",
        metadata=field_metadata(
            required=True,
        ),
    )
    ref: str = ""
    path: str = ""
    file_pattern: str = "*.patch"


@dataclass_json()
@dataclass
class SourceInstallerSchema(BaseInstallerSchema):
    location: Optional[BaseLocationSchema] = field(
        default=None, metadata=field_metadata(required=True)
    )

    # Steps to modify code by patches and others.
    modifier: List[BaseModifierSchema] = field(default_factory=list)

    # This is relative path where kernel source code is located
    kernel_config_file: str = field(
        default="",
        metadata=field_metadata(
            required=False,
        ),
    )


class SourceInstaller(BaseInstaller):
    _code_path: PurePath

    @classmethod
    def type_name(cls) -> str:
        return "source"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return SourceInstallerSchema

    @property
    def _output_names(self) -> List[str]:
        return []

    @property
    def information(self) -> Dict[str, Any]:
        git = self._node.tools[Git]
        lscpu = self._node.tools[Lscpu]
        gcc = self._node.tools[Gcc]
        information = dict()
        if self._code_path:
            information["commit_id"] = git.get_latest_commit_id(cwd=self._code_path)
            information["tag"] = git.get_tag(cwd=self._code_path)
            information["git_repository_url"] = git.get_repo_url(cwd=self._code_path)
            information["git_repository_branch"] = git.get_current_branch(
                cwd=self._code_path
            )
            information["commit_id"] = git.get_latest_commit_id(cwd=self._code_path)
            information["architecture"] = lscpu.get_architecture()
            information["compiler"] = f"gcc {gcc.get_version()}"
            information["build_start_time"] = datetime.now(timezone.utc).isoformat()
            information.update(git.get_latest_commit_details(cwd=self._code_path))
        else:
            self._log.info(
                f"Error retrieving source installer information."
                f"Code path is {self._code_path}."
            )
        return information

    def validate(self) -> None:
        # nothing to validate before source installer started.
        ...

    def install(self) -> str:
        node = self._node
        runbook: SourceInstallerSchema = self.runbook
        assert runbook.location, "the repo must be defined."

        self._install_build_tools(node)

        factory = subclasses.Factory[BaseLocation](BaseLocation)
        source = factory.create_by_runbook(
            runbook=runbook.location, node=node, parent_log=self._log
        )
        self._code_path = source.get_source_code()
        assert node.shell.exists(
            self._code_path
        ), f"cannot find code path: {self._code_path}"
        self._log.info(f"kernel code path: {self._code_path}")

        # modify code
        self._modify_code(node=node, code_path=self._code_path)

        kconfig_file = runbook.kernel_config_file
        self._build_code(
            node=node, code_path=self._code_path, kconfig_file=kconfig_file
        )

        self._install_build(node=node, code_path=self._code_path)

        result = node.execute(
            "make kernelrelease 2>/dev/null",
            cwd=self._code_path,
            shell=True,
        )

        kernel_version = result.stdout
        result.assert_exit_code(
            0,
            f"failed on get kernel version: {kernel_version}",
        )

        # copy current config back to system folder.
        result = node.execute(
            f"cp .config /boot/config-{kernel_version}",
            cwd=self._code_path,
            sudo=True,
        )
        result.assert_exit_code()

        return kernel_version

    def _install_build(self, node: Node, code_path: PurePath) -> None:
        make = node.tools[Make]
        make.make(arguments="modules", cwd=code_path, sudo=True)

        make.make(
            arguments="INSTALL_MOD_STRIP=1 modules_install", cwd=code_path, sudo=True
        )

        make.make(arguments="install", cwd=code_path, sudo=True)

        # The build for Redhat needs extra steps than RPM package. So put it
        # here, not in OS.
        if isinstance(node.os, Redhat):
            result = node.execute("grub2-set-default 0", sudo=True)
            result.assert_exit_code()

            result = node.execute("grub2-mkconfig -o /boot/grub2/grub.cfg", sudo=True)
            result.assert_exit_code()

    def _modify_code(self, node: Node, code_path: PurePath) -> None:
        runbook: SourceInstallerSchema = self.runbook
        if not runbook.modifier:
            return

        modifier_runbooks: List[BaseModifierSchema] = runbook.modifier
        assert isinstance(
            modifier_runbooks, list
        ), f"modifier must be a list, but it's {type(modifier_runbooks)}"

        factory = subclasses.Factory[BaseModifier](BaseModifier)
        for modifier_runbook in modifier_runbooks:
            modifier = factory.create_by_runbook(
                runbook=modifier_runbook,
                node=node,
                code_path=code_path,
                parent_log=self._log,
            )
            self._log.debug(f"modifying code by {modifier.type_name()}")
            modifier.modify()

    def _build_code(self, node: Node, code_path: PurePath, kconfig_file: str) -> None:
        self._log.info("building code...")

        uname = node.tools[Uname]
        kernel_information = uname.get_linux_information()

        cp = node.tools[Cp]
        if kconfig_file:
            kernel_config = code_path.joinpath(kconfig_file)
            err_msg = f"cannot find kernel config path: {kernel_config}"
            assert node.shell.exists(kernel_config), err_msg
            cp.copy(
                src=kernel_config,
                dest=PurePath(".config"),
                cwd=code_path,
            )
        else:
            cp.copy(
                src=node.get_pure_path(
                    f"/boot/config-{kernel_information.kernel_version_raw}"
                ),
                dest=PurePath(".config"),
                cwd=code_path,
            )

        config_path = code_path.joinpath(".config")
        sed = self._node.tools[Sed]
        sed.substitute(
            regexp="CONFIG_DEBUG_INFO_BTF=.*",
            replacement="CONFIG_DEBUG_INFO_BTF=no",
            file=str(config_path),
            sudo=True,
        )

        # workaround failures.
        #
        # make[1]: *** No rule to make target 'debian/canonical-certs.pem',
        # needed by 'certs/x509_certificate_list'.  Stop.
        #
        # make[1]: *** No rule to make target 'certs/rhel.pem', needed by
        # 'certs/x509_certificate_list'.  Stop.
        result = node.execute(
            "scripts/config --disable SYSTEM_TRUSTED_KEYS",
            cwd=code_path,
            shell=True,
        )
        result.assert_exit_code()

        # workaround failures.
        #
        # make[1]: *** No rule to make target 'debian/canonical-revoked-certs.pem',
        # needed by 'certs/x509_revocation_list'.  Stop.
        result = node.execute(
            "scripts/config --disable SYSTEM_REVOCATION_KEYS",
            cwd=code_path,
            shell=True,
        )
        result.assert_exit_code()

        # the gcc version of Redhat 7.x is too old. Upgrade it.
        if isinstance(node.os, Redhat) and node.os.information.version < "8.0.0":
            node.os.install_packages(["devtoolset-8"])
            node.tools[Mv].move("/bin/gcc", "/bin/gcc_back", overwrite=True, sudo=True)
            result.assert_exit_code()
            result = node.execute(
                "ln -s /opt/rh/devtoolset-8/root/usr/bin/gcc /bin/gcc", sudo=True
            )
            result.assert_exit_code()

        make = node.tools[Make]
        make.make(arguments="olddefconfig", cwd=code_path)

        # set timeout to 2 hours
        make.make(arguments="", cwd=code_path, timeout=60 * 60 * 2)

    def _install_build_tools(self, node: Node) -> None:
        os = node.os
        self._log.info("installing build tools")
        if isinstance(os, Redhat):
            for package in list(
                ["elfutils-libelf-devel", "openssl-devel", "dwarves", "bc"]
            ):
                if os.is_package_in_repo(package):
                    os.install_packages(package)
            os.group_install_packages("Development Tools")

            if os.information.version < "8.0.0":
                # git from default CentOS/RedHat 7.x does not support git tag format
                # syntax temporarily use a community repo, then remove it
                node.execute("yum remove -y git", sudo=True)
                node.execute(
                    "rpm -U https://centos7.iuscommunity.org/ius-release.rpm", sudo=True
                )
                os.install_packages("git2u")
                node.execute("rpm -e ius-release", sudo=True)
        elif isinstance(os, Ubuntu):
            # ccache is used to speed up recompilation
            os.install_packages(
                [
                    "git",
                    "build-essential",
                    "bison",
                    "flex",
                    "libelf-dev",
                    "libncurses5-dev",
                    "xz-utils",
                    "libssl-dev",
                    "bc",
                    "ccache",
                ]
            )
        elif isinstance(os, CBLMariner):
            os.install_packages(
                [
                    "build-essential",
                    "bison",
                    "flex",
                    "bc",
                    "ccache",
                    "elfutils-libelf",
                    "elfutils-libelf-devel",
                    "ncurses-libs",
                    "ncurses-compat",
                    "xz",
                    "xz-devel",
                    "xz-libs",
                    "openssl-libs",
                    "openssl-devel",
                ]
            )
        else:
            raise LisaException(
                f"os '{os.name}' doesn't support in {self.type_name()}. "
                f"Implement its build dependencies installation there."
            )


class BaseLocation(subclasses.BaseClassWithRunbookMixin):
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
        self._log = get_logger("kernel_builder", parent=parent_log)

    def get_source_code(self) -> PurePath:
        raise NotImplementedError()


class RepoLocation(BaseLocation):
    @classmethod
    def type_name(cls) -> str:
        return "repo"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return RepoLocationSchema

    def get_source_code(self) -> PurePath:
        runbook = cast(RepoLocationSchema, self.runbook)
        code_path = _get_code_path(runbook.path, self._node, f"{self.type_name()}_code")

        # expand env variables
        echo = self._node.tools[Echo]
        echo_result = echo.run(str(code_path), shell=True)

        code_path = self._node.get_pure_path(echo_result.stdout)

        if runbook.cleanup_code and self._node.shell.exists(code_path):
            self._node.shell.remove(code_path, True)

        # create and give permission on code folder
        self._node.execute(f"mkdir -p {code_path}", sudo=True)
        self._node.execute(f"chmod -R 777 {code_path}", sudo=True)

        self._log.info(f"cloning code from {runbook.repo} to {code_path}...")
        git = self._node.tools[Git]
        code_path = git.clone(
            url=runbook.repo,
            cwd=code_path,
            fail_on_exists=runbook.fail_on_code_exists,
            auth_token=runbook.auth_token,
            timeout=1800,
        )

        git.fetch(cwd=code_path)

        if runbook.ref:
            self._log.info(f"checkout code from: '{runbook.ref}'")
            git.checkout(ref=runbook.ref, cwd=code_path)

        latest_commit_id = git.get_latest_commit_id(cwd=code_path)
        self._log.info(f"Kernel HEAD is now at : {latest_commit_id}")

        return code_path


class LocalLocation(BaseLocation):
    @classmethod
    def type_name(cls) -> str:
        return "local"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return LocalLocationSchema

    def get_source_code(self) -> PurePath:
        runbook: LocalLocationSchema = self.runbook
        return self._node.get_pure_path(runbook.path)


class BaseModifier(subclasses.BaseClassWithRunbookMixin):
    def __init__(
        self,
        runbook: Any,
        node: Node,
        code_path: PurePath,
        parent_log: Logger,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(runbook, *args, **kwargs)
        self._node = node
        self._log = get_logger(self.type_name(), parent=parent_log)
        self._code_path = code_path

    def modify(self) -> None:
        raise NotImplementedError()


class PatchModifier(BaseModifier):
    @classmethod
    def type_name(cls) -> str:
        return "patch"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return PatchModifierSchema

    def modify(self) -> None:
        runbook: PatchModifierSchema = self.runbook

        code_path = _get_code_path(runbook.path, self._node, "patch")

        git = self._node.tools[Git]
        code_path = git.clone(url=runbook.repo, cwd=code_path, ref=runbook.ref)
        patches_path = code_path / runbook.file_pattern
        git.apply(cwd=self._code_path, patches=patches_path)


def _get_code_path(path: str, node: Node, default_name: str) -> PurePath:
    if path:
        code_path = node.get_pure_path(path)
    else:
        code_path = node.working_path / default_name

    return code_path
