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
                
                # Extract actual kernel version and verify files exist
                actual_kernel_version = self._extract_kernel_version_from_rpm(installed_kernel_version)
                self._log.info(f"Extracted kernel version for boot config: {actual_kernel_version}")
                
                # Verify kernel files exist before attempting boot configuration
                if self._verify_kernel_files_exist(node, actual_kernel_version):
                    if isinstance(node.os, CBLMariner) or self._has_grubby_available(node):
                        self._configure_installed_kernel_boot_order(node, actual_kernel_version)
                    else:
                        self._log.warning(f"Skipping boot configuration - OS type {type(node.os)} not supported or grubby not available")
                else:
                    self._log.error(f"Kernel files not found after RPM installation - cannot configure boot")
                    self._log.error(f"Expected kernel files for version: {actual_kernel_version}")
                    # Don't fail the installation completely, but this is a serious issue
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
            actual_version = self._extract_kernel_version_from_rpm(kernel_version)
            
            # Force GRUB configuration update before checking with grubby
            self._log.info("Forcing GRUB configuration update...")
            grub_result = node.execute(
                "grub2-mkconfig -o /boot/grub2/grub.cfg",
                sudo=True,
                expected_exit_code=[0, 1],  # Allow failure
            )
            self._log.info(f"GRUB config update output: {grub_result.stdout}")
            if grub_result.stderr:
                self._log.info(f"GRUB config update stderr: {grub_result.stderr}")
            
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
            
            # Try multiple approaches to set the kernel as default
            # First try: direct kernel path
            result = node.execute(
                f"grubby --set-default={kernel_path}",
                sudo=True,
                expected_exit_code=[0, 1],  # Allow failure for further handling
            )
            
            # If that fails, try with the kernel entry title format
            if result.exit_code != 0:
                self._log.info(f"Direct path failed, trying entry title format...")
                title_result = node.execute(
                    f"grubby --set-default-index=0",  # Set newest kernel first
                    sudo=True,
                    expected_exit_code=[0, 1],
                )
                if title_result.exit_code == 0:
                    result = title_result  # Use this successful result
                    self._log.info("Successfully set kernel using index 0")
            
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
                    # Last resort: Try direct GRUB default setting
                    self._log.info("Attempting direct GRUB default configuration...")
                    self._set_grub_default_directly(node, actual_version)
            
        except Exception as e:
            self._log.warning(f"Failed to configure kernel boot order: {e}")
            # Try fallback methods before giving up
            self._attempt_grub_fallback_methods(node, "0")

    def _set_grub_default_directly(self, node: Node, kernel_version: str) -> None:
        """Directly set GRUB default by modifying GRUB configuration."""
        try:
            # Find the menu entry for our kernel in grub.cfg
            grub_search = node.execute(
                f"grep -n 'menuentry.*{kernel_version}' /boot/grub2/grub.cfg | head -1",
                sudo=True,
                shell=True,
                expected_exit_code=[0, 1],
            )
            
            if grub_search.exit_code == 0 and grub_search.stdout.strip():
                self._log.info(f"Found GRUB menu entry for {kernel_version}: {grub_search.stdout.strip()}")
                
                # Extract menu entry title
                menu_entry_line = grub_search.stdout.strip()
                # Try to extract the menu entry name between quotes
                import re
                menu_match = re.search(r"menuentry ['\"]([^'\"]+)['\"]", menu_entry_line)
                if menu_match:
                    menu_title = menu_match.group(1)
                    self._log.info(f"Extracted menu title: {menu_title}")
                    
                    # Set GRUB_DEFAULT to the menu title (properly escape for shell)
                    import shlex
                    escaped_title = shlex.quote(menu_title)
                    
                    # First backup the current grub config
                    backup_result = node.execute(
                        "sudo cp /etc/default/grub /etc/default/grub.backup",
                        shell=True,
                        expected_exit_code=[0, 1]
                    )
                    
                    # Check file permissions and fix if needed
                    perm_check = node.execute(
                        "sudo ls -la /etc/default/grub",
                        shell=True,
                        expected_exit_code=[0, 1]
                    )
                    self._log.info(f"GRUB config file permissions: {perm_check.stdout.strip()}")
                    
                    # Method 1: Direct file replacement (most reliable)
                    temp_grub_file = "/tmp/grub_default_complete"
                    
                    # Copy existing config and modify it
                    copy_cmd = f"sudo cp /etc/default/grub {temp_grub_file}"
                    copy_result = node.execute(copy_cmd, shell=True, expected_exit_code=[0, 1])
                    
                    if copy_result.exit_code == 0:
                        # Remove any existing GRUB_DEFAULT lines and add new one
                        modify_cmd = f"sudo sed -i '/^GRUB_DEFAULT=/d' {temp_grub_file} && echo 'GRUB_DEFAULT={escaped_title}' | sudo tee -a {temp_grub_file} > /dev/null"
                        modify_result = node.execute(modify_cmd, shell=True, expected_exit_code=[0, 1])
                        
                        if modify_result.exit_code == 0:
                            # Replace the original file
                            replace_cmd = f"sudo cp {temp_grub_file} /etc/default/grub"
                            replace_result = node.execute(replace_cmd, shell=True, expected_exit_code=[0, 1])
                            
                            if replace_result.exit_code == 0:
                                self._log.info(f"Successfully set GRUB_DEFAULT to {escaped_title} via file replacement")
                            else:
                                self._log.warning(f"File replacement failed: {replace_result.stderr}")
                                # Try fallback method
                                self._attempt_grub_fallback_methods(node, "0")
                        else:
                            self._log.warning(f"Temporary file modification failed: {modify_result.stderr}")
                            self._attempt_grub_fallback_methods(node, "0")
                    else:
                        self._log.warning(f"Could not copy GRUB config: {copy_result.stderr}")
                        self._attempt_grub_fallback_methods(node, "0")
                    
                    # Always try fallback methods for maximum reliability
                    self._attempt_grub_fallback_methods(node, "0")
                    
                    # Verify grub config syntax before regenerating
                    verify_syntax = node.execute(
                        "sudo bash -n /etc/default/grub",
                        shell=True,
                        expected_exit_code=[0, 1]
                    )
                    
                    if verify_syntax.exit_code == 0:
                        # Regenerate GRUB configuration
                        grub_regen = node.execute("sudo grub2-mkconfig -o /boot/grub2/grub.cfg", shell=True, expected_exit_code=[0, 1])
                        if grub_regen.exit_code == 0:
                            self._log.info(f"Successfully regenerated GRUB config with new default")
                            
                            # Verify the default was set correctly  
                            verify_cmd = "sudo grub2-editenv list 2>/dev/null | grep saved_entry || echo 'No saved_entry found'"
                            verify_result = node.execute(verify_cmd, shell=True, expected_exit_code=[0, 1])
                            self._log.info(f"GRUB default verification: {verify_result.stdout.strip()}")
                            
                            # Additional verification - check if our kernel is listed first
                            kernel_order_cmd = "sudo grub2-mkconfig -o /dev/stdout 2>/dev/null | grep 'Found linux image' | head -2"
                            order_result = node.execute(kernel_order_cmd, shell=True, expected_exit_code=[0, 1])
                            self._log.info(f"GRUB kernel detection order: {order_result.stdout.strip()}")
                        else:
                            self._log.warning(f"GRUB config regeneration failed: {grub_regen.stderr}")
                            # Don't restore backup here, fallback methods may still work
                    else:
                        self._log.error("GRUB config syntax error detected, restoring backup")
                        node.execute("sudo cp /etc/default/grub.backup /etc/default/grub", shell=True)
                else:
                    self._log.warning("Could not extract menu entry title from GRUB config")
                    # Try fallback methods
                    self._attempt_grub_fallback_methods(node, "0")
            else:
                self._log.warning(f"Could not find menu entry for kernel {kernel_version} in GRUB config")
                # Try fallback methods
                self._attempt_grub_fallback_methods(node, "0")
                
        except Exception as e:
            self._log.warning(f"Direct GRUB configuration failed: {e}")
            # Try fallback methods
            self._attempt_grub_fallback_methods(node, "0")
    
    def _attempt_grub_fallback_methods(self, node: Node, default_value: str) -> None:
        """Attempt multiple GRUB fallback methods for setting boot default."""
        self._log.info(f"Attempting GRUB fallback methods with default value: {default_value}")
        
        # Method 1: grub2-set-default (most reliable)
        try:
            cmd1 = f"sudo grub2-set-default {default_value}"
            result1 = node.execute(cmd1, shell=True, expected_exit_code=[0, 1])
            if result1.exit_code == 0:
                self._log.info(f"Successfully set GRUB default using grub2-set-default {default_value}")
                return
            else:
                self._log.info(f"grub2-set-default failed: {result1.stderr}")
        except Exception as e:
            self._log.info(f"grub2-set-default exception: {e}")
        
        # Method 2: grub2-editenv (direct environment variable)
        try:
            if default_value == "0":
                # Set to boot the first (newest) kernel
                cmd2 = "sudo grub2-editenv - unset saved_entry"
            else:
                # Set specific saved entry
                cmd2 = f"sudo grub2-editenv - set saved_entry='{default_value}'"
            
            result2 = node.execute(cmd2, shell=True, expected_exit_code=[0, 1])
            if result2.exit_code == 0:
                self._log.info(f"Successfully set GRUB environment using grub2-editenv")
                return
            else:
                self._log.info(f"grub2-editenv failed: {result2.stderr}")
        except Exception as e:
            self._log.info(f"grub2-editenv exception: {e}")
        
        # Method 3: Direct file manipulation of grubenv
        try:
            # Check if grubenv exists and can be modified
            grubenv_check = node.execute(
                "sudo ls -la /boot/grub2/grubenv",
                shell=True,
                expected_exit_code=[0, 1, 2]
            )
            
            if grubenv_check.exit_code == 0:
                self._log.info(f"Found grubenv file: {grubenv_check.stdout.strip()}")
                
                # Reset saved_entry to let GRUB use default (first entry)
                cmd3 = "sudo grub2-editenv /boot/grub2/grubenv unset saved_entry"
                result3 = node.execute(cmd3, shell=True, expected_exit_code=[0, 1])
                if result3.exit_code == 0:
                    self._log.info("Successfully reset GRUB environment to use default entry")
                    return
                else:
                    self._log.info(f"Direct grubenv manipulation failed: {result3.stderr}")
        except Exception as e:
            self._log.info(f"grubenv manipulation exception: {e}")
        
        # Method 4: Kernel reordering (ensure our kernel appears first)
        try:
            self._log.info("Attempting kernel reordering to ensure newest kernel is first")
            
            # Force regeneration with verbose output to see kernel order
            regen_cmd = "sudo grub2-mkconfig -o /boot/grub2/grub.cfg"
            regen_result = node.execute(regen_cmd, shell=True, expected_exit_code=[0, 1])
            
            if regen_result.exit_code == 0:
                self._log.info("GRUB configuration regenerated - newest kernel should be default")
                
                # Check the actual order
                check_order_cmd = "sudo grep 'menuentry ' /boot/grub2/grub.cfg | head -3 | grep -o 'Linux [^']*'"
                order_result = node.execute(check_order_cmd, shell=True, expected_exit_code=[0, 1])
                if order_result.exit_code == 0:
                    self._log.info(f"GRUB menu order after regeneration: {order_result.stdout.strip()}")
            else:
                self._log.warning(f"GRUB regeneration failed: {regen_result.stderr}")
        except Exception as e:
            self._log.warning(f"Kernel reordering failed: {e}")
        
        self._log.warning("All GRUB fallback methods attempted - relying on GRUB default behavior")
    
    def _extract_kernel_version_from_rpm(self, rpm_name: str) -> str:
        """Extract the actual kernel version from RPM name."""
        # Handle formats like:
        # kernel-5.15.185.1-2.cm2.x86_64 -> 5.15.185.1-2.cm2
        # kernel-lvbs-6.6.89-9.cm2.x86_64 -> 6.6.89-9.cm2
        if rpm_name.startswith("kernel-lvbs-"):
            # Remove "kernel-lvbs-" prefix and ".x86_64" suffix
            version = rpm_name.replace("kernel-lvbs-", "")
            if ".x86_64" in version:
                version = version.replace(".x86_64", "")
            return version
        elif rpm_name.startswith("kernel-"):
            # Remove "kernel-" prefix and ".x86_64" suffix
            version = rpm_name.replace("kernel-", "")
            if ".x86_64" in version:
                version = version.replace(".x86_64", "")
            return version
        else:
            # Fallback - return as is
            return rpm_name
    
    def _verify_kernel_files_exist(self, node: Node, kernel_version: str) -> bool:
        """Verify that kernel files exist in /boot/ after installation."""
        try:
            # Check for vmlinuz file
            vmlinuz_path = f"/boot/vmlinuz-{kernel_version}"
            vmlinuz_check = node.execute(
                f"ls -la {vmlinuz_path}",
                sudo=True,
                expected_exit_code=[0, 2]
            )
            
            if vmlinuz_check.exit_code == 0:
                self._log.info(f"Found kernel image: {vmlinuz_path}")
                return True
            else:
                self._log.warning(f"Kernel image not found: {vmlinuz_path}")
                
                # Try to find any kernel files with similar version
                search_result = node.execute(
                    f"ls -la /boot/vmlinuz-*{kernel_version}* || ls -la /boot/vmlinuz-* | grep {kernel_version.split('-')[0]}",
                    sudo=True,
                    shell=True,
                    expected_exit_code=[0, 1, 2]
                )
                if search_result.exit_code == 0 and search_result.stdout.strip():
                    self._log.info(f"Found similar kernel files: {search_result.stdout}")
                    # Check if any of the found files match our expected pattern
                    lines = search_result.stdout.strip().split('\n')
                    for line in lines:
                        if f"vmlinuz-{kernel_version}" in line:
                            self._log.info(f"Found exact match in search results: {line}")
                            return True
                else:
                    self._log.warning("No similar kernel files found")
                return False
                
        except Exception as e:
            self._log.error(f"Error checking kernel files: {e}")
            return False


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
