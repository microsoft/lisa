# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import shlex
from typing import Any, Dict, List, Type, cast

from lisa import schema
from lisa.node import Node
from lisa.operating_system import CBLMariner, Linux, Ubuntu
from lisa.tools import Cargo, Git, Ln
from lisa.tools.openvmm import is_missing_command_output
from lisa.util import LisaException, UnsupportedDistroException, subclasses
from lisa.util.logger import Logger


class OpenVmmInstaller(subclasses.BaseClassWithRunbookMixin):
    _command = "openvmm"
    _distro_package_mapping: Dict[str, List[str]] = {}

    @classmethod
    def type_name(cls) -> str:
        return "base"

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

    def get_version(self, command: str = "openvmm") -> str:
        attempts = [
            f"{shlex.quote(command)} --version",
            f"{shlex.quote(command)} --help",
        ]
        for attempt in attempts:
            result = self._node.execute(
                attempt,
                shell=True,
                no_info_log=True,
                no_error_log=True,
                expected_exit_code=None,
            )
            stdout = result.stdout.strip() if result.stdout else ""
            stderr = result.stderr.strip() if result.stderr else ""
            output = stdout or stderr
            normalized_output = output.lower()
            if is_missing_command_output(output):
                continue
            if output and (result.exit_code == 0 or "usage:" in normalized_output):
                return output.splitlines()[0].strip()

        raise LisaException(f"failed to get OpenVMM version from {command}")

    def _create_symlink_to_usr_bin(self, install_path: str) -> None:
        self._node.tools[Ln].create_link(
            target=install_path,
            link="/usr/bin/openvmm",
            is_symbolic=True,
            force=True,
        )


class OpenVmmSourceInstaller(OpenVmmInstaller):
    _distro_package_mapping = {
        Ubuntu.__name__: ["build-essential", "libssl-dev", "perl", "pkg-config"],
        CBLMariner.__name__: [
            "build-essential",
            "gcc",
            "openssl-devel",
            "perl",
            "pkg-config",
            "binutils",
            "glibc-devel",
        ],
    }

    @classmethod
    def type_name(cls) -> str:
        return "source"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        from .schema import OpenVmmSourceInstallerSchema

        return OpenVmmSourceInstallerSchema

    def install(self) -> str:
        from .schema import OpenVmmSourceInstallerSchema

        runbook = cast(OpenVmmSourceInstallerSchema, self.runbook)
        linux = cast(Linux, self._node.os)
        packages_list = self._distro_package_mapping[type(linux).__name__]
        self._log.info(f"installing packages: {packages_list}")
        linux.install_packages(packages_list)

        cargo = self._node.tools[Cargo]
        if not cargo.exists:
            raise LisaException("failed to install cargo for OpenVMM build")

        home_dir = self._node.execute(
            "echo $HOME",
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "failed to determine home directory for OpenVMM build"
            ),
        ).stdout.strip()
        rustup_bin = f"{home_dir}/.cargo/bin/rustup"
        toolchain = cargo.toolchain or "stable"
        self._node.execute(
            "mkdir -p ~/.rustup/downloads ~/.rustup/tmp ~/.cargo/bin",
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "failed to prepare rustup directories for OpenVMM build"
            ),
        )
        self._node.execute(
            f"{shlex.quote(rustup_bin)} component add rust-src --toolchain "
            f"{shlex.quote(toolchain)}",
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "failed to install rust-src component for OpenVMM build"
            ),
        )

        git = self._node.tools[Git]
        code_path = git.clone(
            url=runbook.repo,
            cwd=self._node.working_path,
            ref=runbook.ref,
            auth_token=runbook.auth_token,
            fail_on_exists=False,
        )

        cargo_command = shlex.quote(cargo.command)
        cargo_bin_dir = self._node.get_str_path(
            self._node.get_pure_path(cargo.command).parent
        )
        cargo_env = {
            "OPENSSL_NO_VENDOR": "1",
            "PATH": f"{cargo_bin_dir}:$PATH",
            "RUSTC": f"{cargo_bin_dir}/rustc",
            "RUSTDOC": f"{cargo_bin_dir}/rustdoc",
        }
        restore_packages_cmd = (
            f"{cargo_command} xflowey restore-packages --no-compat-igvm"
        )
        restore_result = self._node.execute(
            restore_packages_cmd,
            shell=True,
            cwd=code_path,
            update_envs=cargo_env,
            no_info_log=True,
            expected_exit_code=None,
        )
        if restore_result.exit_code != 0:
            self._log.warning(
                "OpenVMM dependency restore failed on first attempt; retrying "
                "after refreshing rust-src"
            )
            self._node.execute(
                "mkdir -p ~/.rustup/downloads ~/.rustup/tmp ~/.cargo/bin",
                shell=True,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    "failed to prepare rustup directories for OpenVMM build retry"
                ),
            )
            self._node.execute(
                f"{shlex.quote(rustup_bin)} component add rust-src --toolchain "
                f"{shlex.quote(toolchain)}",
                shell=True,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    "failed to refresh rust-src component for OpenVMM build"
                ),
            )
            self._node.execute(
                restore_packages_cmd,
                shell=True,
                cwd=code_path,
                update_envs=cargo_env,
                no_info_log=True,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    "failed to restore OpenVMM build dependencies"
                ),
            )

        build_cmd = f"{cargo_command} build --release"
        if runbook.features:
            feature_args = ",".join(runbook.features)
            build_cmd = f"{build_cmd} --features {shlex.quote(feature_args)}"

        self._node.execute(
            build_cmd,
            shell=True,
            cwd=code_path,
            update_envs=cargo_env,
            no_info_log=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="failed to build OpenVMM",
        )

        install_parent = self._node.get_str_path(
            self._node.get_pure_path(runbook.install_path).parent
        )
        built_openvmm_path = self._node.get_str_path(
            self._node.get_pure_path(str(code_path)).joinpath(
                "target", "release", "openvmm"
            )
        )
        self._node.execute(
            f"mkdir -p {shlex.quote(install_parent)}",
            shell=True,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "failed to create OpenVMM install directory"
            ),
        )
        self._node.execute(
            (
                "cp "
                f"{shlex.quote(built_openvmm_path)} "
                f"{shlex.quote(runbook.install_path)}"
            ),
            shell=True,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="failed to install OpenVMM",
        )
        self._node.execute(
            f"chmod a+rx {shlex.quote(runbook.install_path)}",
            shell=True,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=("failed to make OpenVMM executable"),
        )
        self._create_symlink_to_usr_bin(runbook.install_path)
        return self.get_version(runbook.install_path)
