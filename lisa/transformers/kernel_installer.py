# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.


import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Type, cast

from assertpy.assertpy import assert_that
from dataclasses_json import dataclass_json

from lisa import notifier, schema
from lisa.messages import KernelBuildMessage
from lisa.node import Node
from lisa.operating_system import Posix, Ubuntu
from lisa.secret import PATTERN_HEADTAIL, add_secret
from lisa.tools import Uname
from lisa.transformers.deployment_transformer import (
    DeploymentTransformer,
    DeploymentTransformerSchema,
)
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
class KernelInstallerTransformerSchema(DeploymentTransformerSchema):
    # the installer's parameters.
    installer: Optional[BaseInstallerSchema] = field(
        default=None, metadata=field_metadata(required=True)
    )
    raise_exception: Optional[bool] = True
    # Set to False if we don't want to fail the process
    # when the kernel version is not changed after installing the kernel.
    # In some scenarios, we don't know the kernel version before the installation and
    # whether the installed kernel version has been tested or not.
    check_kernel_version: Optional[bool] = True


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


class KernelInstallerTransformer(DeploymentTransformer):
    _information_output_name = "information"
    _is_success_output_name = "is_success"

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
        assert runbook.installer, "installer must be defined."

        message = KernelBuildMessage()
        build_sucess: bool = False
        boot_success: bool = False

        node = self._node

        uname = node.tools[Uname]
        kernel_version_before_install = uname.get_linux_information()
        self._log.info(
            f"kernel version before install: {kernel_version_before_install}"
        )
        factory = subclasses.Factory[BaseInstaller](BaseInstaller)
        installer = factory.create_by_runbook(
            runbook=runbook.installer, node=node, parent_log=self._log
        )

        installer.validate()

        try:
            message.old_kernel_version = uname.get_linux_information(
                force_run=True
            ).kernel_version_raw

            installed_kernel_version = installer.install()
            build_sucess = True
            self._information = installer.information
            self._log.info(f"installed kernel version: {installed_kernel_version}")

            # for ubuntu cvm kernel, there is no menuentry added into grub file when
            # the installer's type is "source", it needs to add the menuentry into grub
            # file. Otherwise, the node might not boot into the new kernel especially
            # the installed kernel version is lower than current kernel version.
            from lisa.transformers.dom0_kernel_installer import Dom0Installer
            from lisa.transformers.kernel_source_installer import SourceInstaller
            from lisa.transformers.rpm_kernel_installer import RPMInstaller

            if (
                isinstance(installer, RepoInstaller)
                and "fde" not in installer.runbook.source
            ) or (
                isinstance(installer, SourceInstaller)
                and not isinstance(installer, Dom0Installer)
            ):
                posix = cast(Posix, node.os)
                posix.replace_boot_kernel(installed_kernel_version)
            elif isinstance(installer, RPMInstaller):
                # For kernels installed via RPM, always set as default boot option
                self._log.info(f"Node OS type: {type(node.os)}, name: {node.os.name}")
                from lisa.operating_system import CBLMariner
                if isinstance(node.os, CBLMariner) or self._has_grubby_available(node):
                    self._configure_installed_kernel_boot_order(node, installed_kernel_version)
                else:
                    self._log.warning(f"Skipping boot configuration - OS type {type(node.os)} not supported or grubby not available")
            elif (
                isinstance(installer, RepoInstaller)
                and "fde" in installer.runbook.source
            ):
                # For fde/cvm kernels, it needs to remove the old
                # kernel.efi files after installing the new kernel
                # Ex: /boot/efi/EFI/ubuntu/kernel.efi-6.2.0-1019-azure
                efi_files = node.execute(
                    "ls -t /boot/efi/EFI/ubuntu/kernel.efi-*",
                    sudo=True,
                    shell=True,
                    expected_exit_code=0,
                    expected_exit_code_failure_message=(
                        "fail to find kernel.efi file for kernel type "
                        " linux-image-azure-fde"
                    ),
                )
                for old_efi_file in efi_files.stdout.splitlines()[1:]:
                    self._log.info(f"Removing old kernel efi file: {old_efi_file}")
                    node.execute(
                        f"rm -f {old_efi_file}",
                        sudo=True,
                        shell=True,
                    )

            self._log.info("rebooting")
            node.reboot(time_out=900)
            boot_success = True
            new_kernel_version = uname.get_linux_information(force_run=True)
            message.new_kernel_version = new_kernel_version.kernel_version_raw
            self._log.info(f"kernel version after install: " f"{new_kernel_version}")
            if runbook.check_kernel_version:
                assert_that(
                    new_kernel_version.kernel_version_raw, "Kernel installation Failed"
                ).is_not_equal_to(kernel_version_before_install.kernel_version_raw)
        except Exception as e:
            message.error_message = str(e)
            if runbook.raise_exception:
                raise e
            self._log.info(f"Kernel build failed: {e}")
        finally:
            message.is_success = build_sucess and boot_success
            notifier.notify(message)
        return {
            self._information_output_name: self._information,
            self._is_success_output_name: build_sucess and boot_success,
        }

    def _has_grubby_available(self, node: Node) -> bool:
        """Check if grubby command is available on the system."""
        try:
            result = node.execute(
                "command -v grubby",
                shell=True,
                expected_exit_code=[0, 1],
            )
            available = result.exit_code == 0
            self._log.info(f"Grubby availability check: {available}")
            return available
        except Exception as e:
            self._log.info(f"Grubby availability check failed: {e}")
            return False

    def _configure_installed_kernel_boot_order(self, node: Node, kernel_version: str) -> None:
        """Configure newly installed kernel as default boot option using grubby."""
        try:
            # Extract the actual kernel version from the RPM name
            # Examples:
            # kernel-lvbs-6.6.89-9.cm2.x86_64 -> 6.6.89-9.cm2
            # kernel-5.15.185.1-2.cm2.x86_64 -> 5.15.185.1-2.cm2
            if kernel_version.startswith("kernel-lvbs-"):
                actual_version = kernel_version.replace("kernel-lvbs-", "").rsplit(".", 1)[0]
            elif kernel_version.startswith("kernel-"):
                actual_version = kernel_version.replace("kernel-", "").rsplit(".", 1)[0]
            else:
                actual_version = kernel_version
            
            # First, let's see what kernels grubby can find
            available_kernels = node.execute(
                "grubby --info=ALL | grep '^kernel=' | cut -d= -f2",
                sudo=True,
                shell=True,
            )
            self._log.info(f"Available kernels found by grubby: {available_kernels.stdout}")
            
            # Construct the expected kernel path
            kernel_path = f"/boot/vmlinuz-{actual_version}"
            
            # Check if the kernel file exists
            kernel_check = node.execute(
                f"ls -la {kernel_path}",
                sudo=True,
                expected_exit_code=[0, 2],  # Allow file not found
            )
            
            if kernel_check.exit_code != 0:
                self._log.warning(f"Kernel file {kernel_path} not found, searching for alternatives...")
                # Try to find the kernel by pattern
                kernel_search = node.execute(
                    f"ls -la /boot/vmlinuz-*{actual_version}*",
                    sudo=True,
                    shell=True,
                    expected_exit_code=[0, 2],
                )
                if kernel_search.exit_code == 0:
                    # Extract the first found kernel
                    found_kernels = kernel_search.stdout.strip().split('\n')
                    if found_kernels:
                        # Get the kernel path from the ls output
                        kernel_path = found_kernels[0].split()[-1]
                        self._log.info(f"Found alternative kernel path: {kernel_path}")
            
            # Try to set the kernel as default
            result = node.execute(
                f"grubby --set-default={kernel_path}",
                sudo=True,
                expected_exit_code=[0, 1],  # Allow failure for further handling
            )
            
            if result.exit_code == 0:
                self._log.info(f"Successfully set installed kernel {kernel_path} as default boot entry")
            else:
                # If direct path fails, try using grubby's kernel discovery
                self._log.warning(f"Direct path failed, trying alternative approach: {result.stdout}")
                
                # List all kernels and find the one matching our version
                info_result = node.execute(
                    "grubby --info=ALL",
                    sudo=True,
                )
                
                # Look for our kernel version in the output
                if actual_version in info_result.stdout:
                    self._log.info(f"Found kernel {actual_version} in grubby info, attempting index-based setting")
                    # Try setting by index (newest kernel is usually index 0)
                    index_result = node.execute(
                        "grubby --set-default-index=0",
                        sudo=True,
                        expected_exit_code=[0, 1],
                    )
                    if index_result.exit_code == 0:
                        self._log.info("Successfully set kernel as default using index 0")
                    else:
                        self._log.warning(f"Index-based setting also failed: {index_result.stdout}")
                else:
                    self._log.warning(f"Kernel version {actual_version} not found in grubby info")
            
        except Exception as e:
            self._log.warning(f"Failed to configure kernel boot order: {e}")
            # Don't fail the installation, just log the warning


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

        version_name = release
        # add the repo
        if runbook.is_proposed:
            if "private-ppa" in self.repo_url:
                # 'main' is the only repo component supported by 'private-ppa'
                repo_component = "main"
                repo_entry = f"deb {self.repo_url} {version_name} {repo_component}"
            elif "proposed2" in self.repo_url:
                repo_entry = "ppa:canonical-kernel-team/proposed2"
            else:
                version_name = f"{release}-proposed"
                repo_entry = "ppa:canonical-kernel-team/proposed"
        else:
            repo_entry = f"deb {self.repo_url} {version_name} {repo_component}"

        self._log.info(f"Adding repository: {repo_entry}")
        ubuntu.add_repository(repo_entry)
        full_package_name = runbook.source
        if "fips" in full_package_name:
            # Remove default fips repository before kernel installation.
            # The default fips repository is not needed and it causes
            # the kernel installation from proposed repos to fail.
            self._log.info("Removing repo: https://esm.ubuntu.com/fips/ubuntu")
            ubuntu.remove_repository("https://esm.ubuntu.com/fips/ubuntu")
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
