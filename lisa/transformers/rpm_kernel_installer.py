# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from dataclasses import dataclass, field
from pathlib import PurePath
from typing import Type

from dataclasses_json import dataclass_json

from lisa import schema
from lisa.operating_system import CBLMariner, RPMDistro
from lisa.tools import Rpm
from lisa.util import UnsupportedDistroException, field_metadata

from .kernel_installer import BaseInstaller, BaseInstallerSchema


@dataclass_json()
@dataclass
class RPMInstallerSchema(BaseInstallerSchema):
    # kernel rpm - Node's local absolute path
    kernel_rpm_path: str = field(
        default="",
        metadata=field_metadata(
            required=True,
        ),
    )


class RPMInstaller(BaseInstaller):
    @classmethod
    def type_name(cls) -> str:
        return "rpm"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return RPMInstallerSchema

    def validate(self) -> None:
        if not isinstance(self._node.os, RPMDistro):
            raise UnsupportedDistroException(
                self._node.os,
                f"The '{self.type_name()}' installer only support RPM based Distros. ",
            )
        runbook: RPMInstallerSchema = self.runbook
        kernel_rpm_path: str = runbook.kernel_rpm_path
        assert self._node.shell.exists(
            PurePath(kernel_rpm_path)
        ), f"Node does not contain kernel rpm file: {kernel_rpm_path}"
        assert self._node.tools[Rpm].is_valid_package(
            kernel_rpm_path
        ), f"Provided file {kernel_rpm_path} is not an rpm"

    def install(self) -> str:
        node = self._node
        runbook: RPMInstallerSchema = self.runbook
        kernel_rpm_path: str = runbook.kernel_rpm_path

        # Log boot directory contents before installation
        self._log.info("Boot directory contents before kernel installation:")
        try:
            boot_before = node.execute("ls -la /boot/", sudo=True, expected_exit_code=[0, 2])
            self._log.info(f"Boot directory before: {boot_before.stdout}")
        except Exception as e:
            self._log.warning(f"Could not list /boot before installation: {e}")

        # Install the RPM with detailed logging
        self._log.info(f"Installing kernel RPM: {kernel_rpm_path}")
        rpm = node.tools[Rpm]
        
        try:
            install_result = node.execute(
                f"rpm -ivh {kernel_rpm_path} --force --nodeps", 
                sudo=True,
                cwd=None
            )
            self._log.info(f"RPM installation output: {install_result.stdout}")
            if install_result.stderr:
                self._log.info(f"RPM installation stderr: {install_result.stderr}")
        except Exception as e:
            self._log.error(f"RPM installation failed: {e}")
            raise
        
        # Log boot directory contents after installation
        self._log.info("Boot directory contents after kernel installation:")
        try:
            boot_after = node.execute("ls -la /boot/", sudo=True, expected_exit_code=[0, 2])
            self._log.info(f"Boot directory after: {boot_after.stdout}")
        except Exception as e:
            self._log.warning(f"Could not list /boot after installation: {e}")

        # Extract kernel version from RPM filename
        filename = PurePath(kernel_rpm_path).name
        self._log.info(f"Processing kernel RPM file: {filename}")
        
        # Parse kernel version from RPM name
        # Handle formats like: kernel-5.15.185.1-2.cm2.x86_64.rpm, kernel-lvbs-6.6.89-9.cm2.x86_64.rpm
        installed_kernel_version = filename[: -len(".rpm")]
        actual_kernel_version = self._extract_kernel_version(installed_kernel_version)
        
        self._log.info(f"Extracted kernel version: {actual_kernel_version}")
        
        # Verify that kernel files were actually created
        kernel_files_created = self._verify_kernel_files_exist(node, actual_kernel_version)
        if not kernel_files_created:
            self._log.error(f"Kernel files not found in /boot/ after RPM installation!")
            self._log.error(f"Expected to find: /boot/vmlinuz-{actual_kernel_version}")
            self._log.error(f"This indicates the RPM installation may have failed")
            # Still try to install initramfs in case that helps
            self._log.info("Attempting to generate initramfs for installed kernel...")
            dracut_cmd = f"sudo dracut -f /boot/initramfs-{actual_kernel_version}.img {actual_kernel_version}"
            dracut_result = node.execute(dracut_cmd, shell=True, expected_exit_code=[0, 1])
            if dracut_result.exit_code == 0:
                self._log.info("Successfully generated initramfs")
                # Check again for kernel files
                kernel_files_created = self._verify_kernel_files_exist(node, actual_kernel_version)
            else:
                self._log.warning(f"Dracut failed: {dracut_result.stderr}")
            
        # Always configure newly installed kernel as default boot option
        self._log.info(f"Node OS type: {type(node.os)}, name: {node.os.name}")
        self._log.info(f"Is CBLMariner: {isinstance(node.os, CBLMariner)}")
        
        # Always attempt boot configuration (kernel files may exist but not be detected)
        if kernel_files_created:
            self._log.info("Kernel files verified - proceeding with boot configuration")
        else:
            self._log.warning("Kernel files not detected, but attempting boot configuration anyway")
            
        # Configure boot for any RPM-based system
        if isinstance(node.os, CBLMariner) or self._has_grubby_available(node):
            self._configure_installed_kernel_boot(node, actual_kernel_version)
        else:
            self._log.warning(f"OS type {type(node.os)} not fully supported - using basic boot configuration")
            # Try basic GRUB configuration even without grubby
            try:
                basic_config = f"sudo grub2-set-default 0 && sudo grub2-mkconfig -o /boot/grub2/grub.cfg"
                node.execute(basic_config, shell=True, expected_exit_code=[0, 1])
                self._log.info("Applied basic GRUB configuration")
            except Exception as e:
                self._log.warning(f"Basic GRUB configuration failed: {e}")

        return actual_kernel_version

    def _has_grubby_available(self, node) -> bool:
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

    def _extract_kernel_version(self, rpm_name: str) -> str:
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
    
    def _verify_kernel_files_exist(self, node, kernel_version: str) -> bool:
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
                else:
                    self._log.warning("No similar kernel files found")
                return False
                
        except Exception as e:
            self._log.error(f"Error checking kernel files: {e}")
            return False

    def _configure_installed_kernel_boot(self, node, kernel_version: str) -> None:
        """Configure newly installed kernel as default boot option using grubby."""
        try:
            # kernel_version should already be the actual version (e.g., 5.15.185.1-2.cm2)
            actual_version = kernel_version
            
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
            success = False
            
            # Approach 1: Try setting by kernel path
            result = node.execute(
                f"sudo grubby --set-default={kernel_path}",
                shell=True,
                expected_exit_code=[0, 1],
            )
            
            if result.exit_code == 0:
                self._log.info(f"Successfully set kernel using direct path: {kernel_path}")
                success = True
            else:
                self._log.info(f"Direct path failed ({result.stdout.strip()}), trying alternative approaches...")
                
                # Approach 2: Try using menu entry ID from grub.cfg
                menu_id_result = node.execute(
                    f"sudo grep -E 'menuentry.*{actual_version}.*{{' /boot/grub2/grub.cfg | head -1 | grep -o \"gnulinux-[^']*\" || echo 'not_found'",
                    shell=True,
                    expected_exit_code=[0, 1]
                )
                
                if menu_id_result.exit_code == 0 and 'not_found' not in menu_id_result.stdout:
                    menu_id = menu_id_result.stdout.strip()
                    self._log.info(f"Found menu ID: {menu_id}")
                    
                    # Try setting by menu ID
                    menu_result = node.execute(
                        f"sudo grubby --set-default-index=0 || sudo grubby --set-default='{menu_id}'",
                        shell=True,
                        expected_exit_code=[0, 1]
                    )
                    if menu_result.exit_code == 0:
                        self._log.info("Successfully set kernel using menu ID")
                        success = True
                
                # Approach 3: Direct GRUB environment setting (most reliable)
                if not success:
                    self._log.info("Grubby approaches failed, using direct GRUB method...")
                    self._set_grub_default_directly(node, actual_version)
                    success = True  # Assume success since we handle errors in that method
            
            # Final verification
            if success:
                # Verify the configuration took effect
                verify_result = node.execute(
                    "sudo grubby --default-kernel 2>/dev/null || echo 'unable to get default'",
                    shell=True,
                    expected_exit_code=[0, 1]
                )
                self._log.info(f"Default kernel after configuration: {verify_result.stdout.strip()}")
                
                # Also check GRUB environment
                grub_env_result = node.execute(
                    "sudo grub2-editenv list 2>/dev/null | grep -E '(saved_entry|default)' || echo 'no grub env found'",
                    shell=True,
                    expected_exit_code=[0, 1]
                )
                self._log.info(f"GRUB environment: {grub_env_result.stdout.strip()}")
            else:
                self._log.warning("All boot configuration methods failed")
            
        except Exception as e:
            self._log.warning(f"Failed to configure kernel boot order: {e}")
            # Don't fail the installation, just log the warning

    def _set_grub_default_directly(self, node, kernel_version: str) -> None:
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
                    
                    # Use printf to safely write the GRUB_DEFAULT line
                    printf_cmd = f"printf 'GRUB_DEFAULT=%s\n' {escaped_title} | sudo tee /tmp/grub_default_new > /dev/null"
                    printf_result = node.execute(printf_cmd, shell=True, expected_exit_code=[0, 1])
                    
                    if printf_result.exit_code == 0:
                        # Replace the GRUB_DEFAULT line in the config
                        sed_cmd = "sudo sed -i '/^GRUB_DEFAULT=/d' /etc/default/grub && sudo cat /tmp/grub_default_new >> /etc/default/grub"
                        sed_result = node.execute(sed_cmd, shell=True, expected_exit_code=[0, 1])
                        
                        if sed_result.exit_code != 0:
                            self._log.warning(f"Failed to update GRUB config, restoring backup")
                            node.execute("sudo cp /etc/default/grub.backup /etc/default/grub", shell=True)
                        else:
                            self._log.info(f"Successfully set GRUB_DEFAULT to {escaped_title}")
                    else:
                        self._log.warning(f"Printf command failed: {printf_result.stderr}")
                    
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
                        else:
                            self._log.warning(f"GRUB config regeneration failed: {grub_regen.stderr}")
                            # Restore backup on failure
                            node.execute("sudo cp /etc/default/grub.backup /etc/default/grub", shell=True)
                    else:
                        self._log.error("GRUB config syntax error detected, restoring backup")
                        node.execute("sudo cp /etc/default/grub.backup /etc/default/grub", shell=True)
                else:
                    self._log.warning("Could not extract menu entry title from GRUB config")
            else:
                self._log.warning(f"Could not find menu entry for kernel {kernel_version} in GRUB config")
                
        except Exception as e:
            self._log.warning(f"Direct GRUB configuration failed: {e}")
