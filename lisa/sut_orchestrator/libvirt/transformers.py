# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from dataclasses import dataclass, field
from pathlib import PurePath
from typing import Any, Dict, List, Optional, Type, cast

from dataclasses_json import dataclass_json

from lisa import schema
from lisa.node import Node, quick_connect
from lisa.operating_system import CBLMariner, Linux, Ubuntu
from lisa.tools import Git, Wget
from lisa.transformer import Transformer
from lisa.util import (
    UnsupportedDistroException,
    field_metadata,
    filter_ansi_escape,
    subclasses,
)
from lisa.util.logger import Logger
from lisa.util.process import ExecutableResult


@dataclass_json()
@dataclass
class BaseInstallerSchema(schema.TypedSchema, schema.ExtendableSchemaMixin):
    ...


@dataclass_json()
@dataclass
class SourceInstallerSchema(BaseInstallerSchema):
    # source code repo
    repo: str = ""
    ref: str = ""


@dataclass_json
@dataclass
class InstallerTransformerSchema(schema.Transformer):
    # SSH connection information to the node
    connection: Optional[schema.RemoteNode] = field(
        default=None, metadata=field_metadata(required=True)
    )
    # installer's parameters.
    installer: Optional[BaseInstallerSchema] = field(
        default=None, metadata=field_metadata(required=True)
    )
    # libvirt installer parameters
    libvirt: Optional[BaseInstallerSchema] = field(
        default=None, metadata=field_metadata(required=False)
    )


class BaseInstaller(subclasses.BaseClassWithRunbookMixin):
    _command = ""
    _distro_package_mapping: Dict[str, List[str]] = {}

    @classmethod
    def type_name(cls) -> str:
        return "base_installer"

    def __init__(
        self,
        runbook: Any,
        node: Node,
        log: Logger,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(runbook, *args, **kwargs)
        self._node = node
        self._log = log

    def validate(self) -> None:
        if type(self._node.os).__name__ not in self._distro_package_mapping:
            raise UnsupportedDistroException(
                self._node.os,
                f"'{self.type_name()}' installer is not supported.",
            )

    def install(self) -> str:
        raise NotImplementedError()

    def _run_command(self) -> ExecutableResult:
        return self._node.execute(f"{self._command} --version", shell=True)

    def _get_version(self) -> str:
        result = self._run_command()
        result_output = filter_ansi_escape(result.stdout)
        return result_output

    def _is_installed(self) -> bool:
        result = self._run_command()
        return result.exit_code == 0


class QemuInstaller(BaseInstaller):
    _command = "qemu-system-x86_64"


class CloudHypervisorInstaller(BaseInstaller):
    _command = "cloud-hypervisor"


class LibvirtInstaller(BaseInstaller):
    _command = "libvirtd"


class QemuInstallerTransformer(Transformer):
    @classmethod
    def type_name(cls) -> str:
        return "qemu_installer"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return InstallerTransformerSchema

    @property
    def _output_names(self) -> List[str]:
        return []

    def _internal_run(self) -> Dict[str, Any]:
        runbook: InstallerTransformerSchema = self.runbook
        assert runbook.connection, "connection must be defined."
        assert runbook.installer, "installer must be defined."

        node = quick_connect(runbook.connection, "qemu_installer_node")

        factory = subclasses.Factory[QemuInstaller](QemuInstaller)
        installer = factory.create_by_runbook(
            runbook=runbook.installer,
            node=node,
            log=self._log,
        )
        if not installer._is_installed():
            installer.validate()
            qemu_version = installer.install()
            self._log.info(f"installed qemu version: {qemu_version}")
            node.reboot()
        else:
            qemu_version = installer._get_version()
            self._log.info(f"Already installed! qemu version: {qemu_version}")

        if runbook.libvirt:
            _install_libvirt(runbook.libvirt, node, self._log)

        return {}


class CloudHypervisorInstallerTransformer(Transformer):
    @classmethod
    def type_name(cls) -> str:
        return "cloudhypervisor_installer"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return InstallerTransformerSchema

    @property
    def _output_names(self) -> List[str]:
        return []

    def _internal_run(self) -> Dict[str, Any]:
        runbook: InstallerTransformerSchema = self.runbook
        assert runbook.connection, "connection must be defined."
        assert runbook.installer, "installer must be defined."

        node = quick_connect(runbook.connection, "cloudhypervisor_installer_node")

        factory = subclasses.Factory[CloudHypervisorInstaller](CloudHypervisorInstaller)
        installer = factory.create_by_runbook(
            runbook=runbook.installer,
            node=node,
            log=self._log,
        )
        if not installer._is_installed():
            installer.validate()
            ch_version = installer.install()
            self._log.info(f"installed cloud-hypervisor version: {ch_version}")
            node.reboot()
        else:
            ch_version = installer._get_version()
            self._log.info(f"Already installed! cloud-hypervisor version: {ch_version}")

        if runbook.libvirt:
            _install_libvirt(runbook.libvirt, node, self._log)

        return {}


class LibvirtPackageInstaller(LibvirtInstaller):

    _distro_package_mapping = {
        Ubuntu.__name__: ["libvirt-daemon-system"],
        CBLMariner.__name__: ["dnsmasq", "ebtables", "libvirt"],
    }

    @classmethod
    def type_name(cls) -> str:
        return "package"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return BaseInstallerSchema

    def install(self) -> str:
        node: Node = self._node
        linux: Linux = cast(Linux, node.os)
        packages_list = self._distro_package_mapping[type(linux).__name__]
        self._log.info(f"installing packages: {packages_list}")
        linux.install_packages(list(packages_list))
        return self._get_version()


class QemuPackageInstaller(QemuInstaller):

    _distro_package_mapping = {
        Ubuntu.__name__: ["qemu-kvm"],
        CBLMariner.__name__: ["qemu-kvm"],
    }

    @classmethod
    def type_name(cls) -> str:
        return "package"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return BaseInstallerSchema

    def install(self) -> str:
        node: Node = self._node
        linux: Linux = cast(Linux, node.os)
        packages_list = self._distro_package_mapping[type(linux).__name__]
        self._log.info(f"installing packages: {packages_list}")
        linux.install_packages(list(packages_list))
        return self._get_version()


class CloudHypervisorPackageInstaller(CloudHypervisorInstaller):

    _distro_package_mapping = {
        CBLMariner.__name__: ["cloud-hypervisor"],
    }

    @classmethod
    def type_name(cls) -> str:
        return "package"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return BaseInstallerSchema

    def install(self) -> str:
        node: Node = self._node
        linux: Linux = cast(Linux, node.os)
        packages_list = self._distro_package_mapping[type(linux).__name__]
        self._log.info(f"installing packages: {packages_list}")
        linux.install_packages(list(packages_list))
        return self._get_version()


class LibvirtSourceInstaller(LibvirtInstaller):

    _distro_package_mapping = {
        Ubuntu.__name__: [
            "ninja-build",
            "dnsmasq-base",
            "libxml2-utils",
            "xsltproc",
            "python3-docutils",
            "libglib2.0-dev",
            "libgnutls28-dev",
            "libxml2-dev",
            "libnl-3-dev",
            "libnl-route-3-dev",
            "libtirpc-dev",
            "libyajl-dev",
            "libcurl4-gnutls-dev",
            "python3-pip",
        ],
        CBLMariner.__name__: [
            "ninja-build",
            "build-essential",
            "rpcsvc-proto",
            "python3-docutils",
            "glibc-devel",
            "glib-devel",
            "gnutls-devel",
            "libnl3-devel",
            "libtirpc-devel",
            "curl-devel",
            "ebtables",
            "yajl-devel",
            "python3-pip",
            "dnsmasq",
            "nmap-ncat",
        ],
    }

    @classmethod
    def type_name(cls) -> str:
        return "source"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return SourceInstallerSchema

    def _build_and_install(self, code_path: PurePath) -> None:
        self._node.execute(
            "meson build -D driver_ch=enabled -D driver_qemu=disabled \\"
            "-D driver_openvz=disabled -D driver_esx=disabled \\"
            "-D driver_vmware=disabled  -D driver_lxc=disabled \\"
            "-D driver_libxl=disabled -D driver_vbox=disabled \\"
            "-D selinux=disabled -D system=true --prefix=/usr \\"
            "-D git_werror=disabled",
            cwd=code_path,
            shell=True,
            sudo=True,
        )
        self._node.execute(
            "ninja -C build",
            shell=True,
            sudo=True,
            cwd=code_path,
            expected_exit_code=0,
            expected_exit_code_failure_message="'ninja -C build' command failed.",
        )
        self._node.execute(
            "ninja -C build install",
            shell=True,
            sudo=True,
            cwd=code_path,
            expected_exit_code=0,
            expected_exit_code_failure_message="'ninja -C install' command failed.",
        )
        self._node.execute("ldconfig", shell=True, sudo=True)

    def _install_dependencies(self) -> None:
        linux: Linux = cast(Linux, self._node.os)
        dep_packages_list = self._distro_package_mapping[type(linux).__name__]
        linux.install_packages(list(dep_packages_list))
        result = self._node.execute("pip3 install meson", shell=True, sudo=True)
        assert not result.exit_code, "Failed to install meson"

    def install(self) -> str:
        runbook: SourceInstallerSchema = self.runbook
        self._log.info("Installing dependencies for Libvirt...")
        self._install_dependencies()
        self._log.info("Cloning source code of Libvirt...")
        code_path = _get_source_code(runbook, self._node, self.type_name(), self._log)
        self._log.info("Building source code of Libvirt...")
        self._build_and_install(code_path)
        return self._get_version()


class CloudHypervisorSourceInstaller(CloudHypervisorInstaller):

    _distro_package_mapping = {
        Ubuntu.__name__: ["gcc"],
        CBLMariner.__name__: ["gcc", "binutils", "glibc-devel"],
    }

    @classmethod
    def type_name(cls) -> str:
        return "source"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return SourceInstallerSchema

    def _build_and_install(self, code_path: PurePath) -> None:
        self._node.execute(
            "cargo build --release",
            shell=True,
            sudo=False,
            cwd=code_path,
            expected_exit_code=0,
            expected_exit_code_failure_message="Failed to build cloud-hypervisor",
        )
        self._node.execute(
            "cp ./target/release/cloud-hypervisor /usr/local/bin",
            shell=True,
            sudo=True,
            cwd=code_path,
        )
        self._node.execute(
            "chmod a+rx /usr/local/bin/cloud-hypervisor",
            shell=True,
            sudo=True,
        )
        self._node.execute(
            "setcap cap_net_admin+ep /usr/local/bin/cloud-hypervisor",
            shell=True,
            sudo=True,
        )

    def _install_dependencies(self) -> None:
        linux: Linux = cast(Linux, self._node.os)
        packages_list = self._distro_package_mapping[type(linux).__name__]
        linux.install_packages(list(packages_list))
        self._node.execute(
            "curl https://sh.rustup.rs -sSf | sh -s -- -y",
            shell=True,
            sudo=False,
            expected_exit_code=0,
            expected_exit_code_failure_message="Failed to install Rust & Cargo",
        )
        self._node.execute("source ~/.cargo/env", shell=True, sudo=False)
        if isinstance(self._node.os, Ubuntu):
            output = self._node.execute("echo $HOME", shell=True)
            path = self._node.get_pure_path(output.stdout)
            self._node.execute(
                "cp .cargo/bin/* /usr/local/bin/",
                shell=True,
                sudo=True,
                cwd=path,
            )
        self._node.execute("cargo --version", shell=True)

    def install(self) -> str:
        runbook: SourceInstallerSchema = self.runbook
        self._log.info("Installing dependencies for Cloudhypervisor...")
        self._install_dependencies()
        self._log.info("Cloning source code of Cloudhypervisor ...")
        code_path = _get_source_code(runbook, self._node, self.type_name(), self._log)
        self._log.info("Building source code of Cloudhypervisor...")
        self._build_and_install(code_path)
        return self._get_version()


class CloudHypervisorBinaryInstaller(CloudHypervisorInstaller):

    _distro_package_mapping = {
        Ubuntu.__name__: ["jq"],
        CBLMariner.__name__: ["jq"],
    }

    @classmethod
    def type_name(cls) -> str:
        return "binary"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return BaseInstallerSchema

    def install(self) -> str:
        linux: Linux = cast(Linux, self._node.os)
        packages_list = self._distro_package_mapping[type(linux).__name__]
        self._log.info(f"installing packages: {packages_list}")
        linux.install_packages(list(packages_list))
        command = (
            "curl -s https://api.github.com/repos/cloud-hypervisor/"
            "cloud-hypervisor/releases/latest | jq -r '.tag_name'"
        )
        latest_release_tag = self._node.execute(command, shell=True)
        self._log.debug(f"latest tag: {latest_release_tag}")
        wget = self._node.tools[Wget]
        file_url = (
            "https://github.com/cloud-hypervisor/cloud-hypervisor/"
            f"releases/download/{latest_release_tag}/cloud-hypervisor"
        )
        file_path = wget.get(
            url=file_url,
            executable=True,
            filename="cloud-hypervisor",
        )
        self._node.execute(f"cp {file_path} /usr/local/bin", sudo=True)
        self._node.execute(
            "chmod a+rx /usr/local/bin/cloud-hypervisor",
            shell=True,
            sudo=True,
        )
        self._node.execute(
            "setcap cap_net_admin+ep /usr/local/bin/cloud-hypervisor",
            sudo=True,
        )
        return self._get_version()


def _get_source_code(
    runbook: SourceInstallerSchema, node: Node, default_name: str, log: Logger
) -> PurePath:
    code_path = node.working_path
    log.debug(f"cloning code from {runbook.repo} to {code_path}...")
    git = node.tools[Git]
    code_path = git.clone(url=runbook.repo, cwd=code_path, ref=runbook.ref)
    return code_path


def _install_libvirt(runbook: schema.TypedSchema, node: Node, log: Logger) -> None:
    libvirt_factory = subclasses.Factory[LibvirtInstaller](LibvirtInstaller)
    libvirt_installer = libvirt_factory.create_by_runbook(
        runbook=runbook,
        node=node,
        log=log,
    )
    if not libvirt_installer._is_installed():
        libvirt_installer.validate()
        libvirt_version = libvirt_installer.install()
        log.info(f"installed libvirt version: {libvirt_version}")

        if isinstance(node.os, Ubuntu):
            node.execute("systemctl disable apparmor", shell=True, sudo=True)
        node.execute("systemctl enable libvirtd", shell=True, sudo=True)
        node.reboot()
    else:
        libvirt_version = libvirt_installer._get_version()
        log.info(f"Already installed! libvirt version: {libvirt_version}")
