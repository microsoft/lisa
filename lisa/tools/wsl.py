# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
import time
from pathlib import PurePath
from typing import TYPE_CHECKING, Any, Dict, Optional

import charset_normalizer
from assertpy.assertpy import assert_that

from lisa.executable import Tool
from lisa.tools import PowerShell
from lisa.util import LisaException, create_timer, find_groups_in_lines
from lisa.util.process import ExecutableResult, Process

from . import Echo, Find, Ls, Tar

if TYPE_CHECKING:
    from lisa.node import Node


class Wsl(Tool):
    """
    Support commands on WSL host and WSL both.
    """

    FIXED_WSL_PATH = r"%ProgramFiles%\wsl\wsl.exe"
    CONFIG_FILE_PATH = r"%USERPROFILE%\.wslconfig"

    ENCODING = "utf-16-le"
    INSTALL_TIMEOUT = 600

    def __init__(self, node: "Node", guest: "Node") -> None:
        assert guest, "guest node is required for Wsl tool."
        super().__init__(node=node)
        self._guest = guest
        self._command_path = "wsl"

    @property
    def command(self) -> str:
        return self._command_path

    @property
    def can_install(self) -> bool:
        return True

    def install(self) -> bool:
        self._log.debug("wsl is not detected, or version is low. Installing...")
        if self.node.is_remote:
            self._install_on_remote()
        else:
            self._install_on_local()

        return self._check_exists()

    def _add_lisatest_user(self, distro: str) -> None:
        # Check if lisatest user already exists (use simple command)
        check_user_cmd = """ -u root -- id lisatest """
        try:
            check_result = self._wsl_execute(
                check_user_cmd, distro=distro, no_info_log=True
            )
            user_exists = check_result.exit_code == 0
        except Exception:
            user_exists = False

        if user_exists:
            self._log.debug("lisatest user already exists, updating configuration...")
            # User exists, just update sudoers and wsl.conf
            update_config_cmd = (
                """ -u root -- bash -c "echo 'lisatest ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/lisatest; """
                """printf '[user]\\ndefault=lisatest\\n' > /etc/wsl.conf" """
            )
            result = self._wsl_execute(update_config_cmd, distro=distro)
        else:
            self._log.debug("Creating lisatest user...")
            # User doesn't exist, create it
            # Also disable cloud-init since it doesn't work properly in WSL
            add_lisatest_cmd = (
                """ -u root -- bash -c "useradd -m -s /bin/bash lisatest  && """
                """echo 'lisatest ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/lisatest; """
                """printf '[user]\\ndefault=lisatest\\n' > /etc/wsl.conf; """
                """touch /etc/cloud/cloud-init.disabled" """
            )
            result = self._wsl_execute(add_lisatest_cmd, distro=distro)

        result.assert_exit_code(
            expected_exit_code=0,
            message="wsl add lisatest account failed",
            include_output=True,
        )

    def install_distro(
        self,
        name: str,
        reinstall: bool = False,
        kernel: str = "",
        enable_debug_console: bool = False,
    ) -> None:
        is_installed = False

        if reinstall:
            self._wsl_execute(
                f"--unregister {name}",
            )

        # Ubuntu (Default)
        distro_name_pattern = re.compile(rf"^\s*(?P<name>{name})\s*?.*?$")
        result = self._wsl_execute("--list --all", timeout=30)
        matched = find_groups_in_lines(result.stdout, distro_name_pattern)
        if matched:
            self._log.info(f"{name} is already installed, verifying it's ready...")
            is_installed = True

            # Even if distro is registered, it might still be provisioning
            # Wait for it to be ready to accept commands (give it up to 5 minutes for Azure)
            self._wait_for_distro_ready(name, timeout=300)
            time.sleep(10)
            self._add_lisatest_user(name)

        # set debug console and replace kernel
        self._config(enable_debug_console=enable_debug_console, kernel=kernel)

        # shutdown to make new kernel effective after configured. If the kernel
        # is not configured, the original kernel will be loaded.
        self.shutdown_wsl()

        if not is_installed:
            install_process = self._wsl_execute_async(
                f"--install -d {name} --no-launch", encoding="utf-8"
            )

            # 1st, wait for Ubuntu to appear in wsl --list (basic installation complete)
            self._wait_for_distro_registration(name)
            time.sleep(10)

            # 2nd, Wait a bit more and verify distro is actually usable
            self._wait_for_distro_ready(name, timeout=300)
            # use powershell to kill and restart wsl due to OOBE stuck
            # self._kill_restart_wsl()

            # 3rd Now add user (Ubuntu is ready and can execute commands)
            self._add_lisatest_user(name)

            # 4th, wait for full provisioning to complete
            elapsed = create_timer()
            done = False
            self._log.debug(f"Waiting for {name} provisioning to complete...")
            while elapsed.elapsed(False) < self.INSTALL_TIMEOUT:
                if self._check_install_done(distro=name):
                    done = True
                    break
                time.sleep(1)

            # raise error if not done
            if not done:
                self._check_install_done(distro=name, raise_error=True)

            self.shutdown_distro(name)

            # kill may not be success in Windows. But it prevents more output
            # from this commands.
            install_process.kill()

        self.reload_guest_os()

        if not is_installed:
            # set NOPASSWD
            echo = self._guest.tools[Echo]
            echo.write_to_file(
                "sudo ALL=(ALL:ALL) NOPASSWD:ALL",
                self._guest.get_pure_path("/etc/sudoers"),
                append=True,
            )

    def _kill_restart_wsl(self) -> None:
        self._log.debug("Killing and restarting WSL to avoid OOBE stuck...")
        kill_wsl_cmd = (
            "taskkill /f /fi 'imagename eq wsl*';"
            " taskkill /f /im wslhost.exe; taskkill /f /im vmmem"
        )
        self.node.tools[PowerShell].run_cmdlet(
            kill_wsl_cmd,
            force_run=True,
        )
        time.sleep(5)

        self.node.tools[PowerShell].run_cmdlet(
            "Restart-Service LxssManager",
            force_run=True,
        )
        time.sleep(5)

    def normalize_result(self, result: ExecutableResult) -> ExecutableResult:
        # wsl output is utf-16-le, but Windows returns utf-8. The logic is to
        # try best to normalize, but still possible not to be normalized. So
        # calling this method to normalize output explicitly.
        encoding = charset_normalizer.detect(result.stdout.encode())["encoding"]
        if encoding != "utf-8":
            assert isinstance(encoding, str), f"actual {type(encoding)}"
            result.stdout = result.stdout.encode(encoding).decode()
            result.stderr = result.stderr.encode(encoding).decode()

        return result

    def shutdown_distro(self, distro: str) -> None:
        self._log.debug(f"shutting down distro {distro}")
        self._wsl_execute(f"--terminate {distro}")

    def shutdown_wsl(self) -> None:
        self._log.debug("shutting down WSL.")
        self._wsl_execute("--shutdown")

    def _wait_for_distro_registration(self, name: str, waittime: int = 300) -> None:
        """Wait for distro to appear in wsl --list (basic installation complete)."""
        elapsed = create_timer()
        distro_registered = False
        self._log.debug(f"Waiting for {name} distro registered in WSL...")
        while elapsed.elapsed(False) < waittime:
            result = self._wsl_execute("--list --all", no_info_log=True, timeout=30)
            distro_name_pattern = re.compile(rf"^\s*(?P<name>{name})\s*?.*?$")
            matched = find_groups_in_lines(result.stdout, distro_name_pattern)
            if matched:
                self._log.debug(
                    f"{name} is now registered, took {elapsed.elapsed()} seconds"
                )
                distro_registered = True
                break
            time.sleep(5)

        if not distro_registered:
            raise LisaException(
                f"Timeout waiting for {name} to be registered after {waittime} seconds"
            )

    def _wait_for_distro_ready(self, name: str, timeout: int = 300) -> None:
        """Wait for distro to be ready to accept commands.

        There's a race condition: distro appears in list but WSL service
        hasn't fully registered it yet.
        """
        self._log.debug(f"Verifying {name} distro ready to accept commands...")
        elapsed = create_timer()
        distro_ready = False
        while elapsed.elapsed(False) < timeout:
            try:
                # Use a longer timeout to avoid killing wsl process during distro startup
                # The outer loop controls the overall timeout
                result = self._wsl_execute(
                    " -u root -- true", distro=name, no_info_log=True, timeout=240
                )
                if result.exit_code == 0:
                    self._log.debug(
                        f"{name} is ready after {elapsed.elapsed()} seconds"
                    )
                    distro_ready = True
                    break
                elif "WSL_E_DISTRO_NOT_FOUND" in result.stdout:
                    self._log.debug(
                        f"Distro {name} not found yet, waiting... (elapsed: {elapsed.elapsed()}s)"
                    )
                else:
                    self._log.debug(
                        f"Distro not ready, exit_code={result.exit_code}, stdout={result.stdout[:100]}"
                    )
            except Exception as e:
                self._log.debug(f"Distro not ready yet: {e}")
            time.sleep(5)

        if not distro_ready:
            raise LisaException(
                f"Timeout waiting for {name} to be ready to accept commands"
            )

    def reload_guest_os(self) -> None:
        from lisa.operating_system import OperatingSystem

        self._guest.os = OperatingSystem.create(self._guest)

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        super()._initialize(*args, **kwargs)
        if not hasattr(self.node, "os") or not self.node.os.is_windows:
            raise LisaException("wsl is only available on Windows")

    def _check_exists(self) -> bool:
        self._detect_installed_path()

        # detecting version, and check if current version support --version
        # parameter. The version command may not work, use utf-8 to see Windows
        # error.
        result = self._wsl_execute("--version", encoding="utf-8")

        return result.exit_code == 0

    def _detect_installed_path(self) -> bool:
        is_found = False

        if not self.node.is_remote:
            # local doesn't have OPENSSH issue, use default path.
            self._command_path = "wsl"
            return True

        fixed_wsl_path = self.node.expand_env_path(self.FIXED_WSL_PATH)
        self._log.debug(f"try to detect wsl path: {fixed_wsl_path}")
        exists, _ = self.command_exists(fixed_wsl_path)
        if exists:
            # quote the path, because it may have space.
            self._command_path = f'"{fixed_wsl_path}"'
            is_found = True
            self._log.debug(f"detected wsl path: {self._command_path}")

        return is_found

    def _wsl_execute(
        self,
        cmd: str,
        distro: str = "",
        shell: bool = False,
        in_wsl: bool = False,
        no_info_log: bool = False,
        encoding: str = "",
        timeout: float = 300,
    ) -> ExecutableResult:
        process = self._wsl_execute_async(
            cmd,
            distro=distro,
            shell=shell,
            in_wsl=in_wsl,
            no_info_log=no_info_log,
            encoding=encoding,
        )
        result = process.wait_result(timeout=timeout)
        result = self.normalize_result(result)

        return result

    def _wsl_execute_async(
        self,
        cmd: str,
        distro: str = "",
        shell: bool = False,
        sudo: bool = False,
        nohup: bool = False,
        no_error_log: bool = False,
        no_info_log: bool = False,
        no_debug_log: bool = False,
        cwd: Optional[PurePath] = None,
        update_envs: Optional[Dict[str, str]] = None,
        in_wsl: bool = False,
        encoding: str = "",
    ) -> Process:
        if distro:
            command = f"{self.command} -d {distro}"
        else:
            command = self.command

        if in_wsl:
            command = f"{command} --"

        command = f"{command} {cmd}"
        if not encoding:
            encoding = "" if in_wsl else self.ENCODING

        self._log.debug(f"---paxue debug--- execute wsl cmd: {command}")
        process = self.node.execute_async(
            command,
            nohup=nohup,
            no_error_log=no_error_log,
            no_info_log=no_info_log,
            no_debug_log=no_debug_log,
            encoding=encoding,
        )

        return process

    def _install_on_remote(self) -> None:
        # Use --no-distribution to explicitly install only WSL components
        # install a default distribution may not work in remote SSH session.
        self._wsl_execute("--install --no-distribution", encoding="utf-8")
        self.node.reboot()
        # time.sleep(120)

        # trigger a wsl command to make sure wsl is ready.
        self._wsl_execute("--version")

    def _install_on_local(self) -> None:
        self._wsl_execute("--install -n")

        self._wsl_execute("--update --pre-release")

    def _check_install_done(self, distro: str, raise_error: bool = False) -> bool:
        result = self._wsl_execute(
            "echo installed", distro=distro, in_wsl=True, no_info_log=True
        )

        if raise_error:
            result.assert_exit_code(
                expected_exit_code=0, message="wsl install failed", include_output=True
            )

        return result.exit_code == 0 and result.stdout == "installed"

    def _config(
        self,
        enable_debug_console: bool = False,
        kernel: str = "",
    ) -> None:
        config_file = self.node.expand_env_path(self.CONFIG_FILE_PATH)

        content = "[wsl2]\n"
        # set debug console
        if enable_debug_console:
            content += "debugConsole=true\n"

        # replace kernel
        if kernel:
            kernel_path = self._config_kernel(kernel)
            content += f"kernel={kernel_path}"

        # reset it always
        echo = self.node.tools[Echo]
        echo.write_to_file(
            content, file=self.node.get_pure_path(config_file), ignore_error=False
        )
        self._log.debug(f"Generated config content:\n{content}")

    def _config_kernel(self, kernel: str) -> str:
        self._log.debug(f"Detecting kernel from {kernel}")

        if not self.node.shell.exists(PurePath(kernel)):
            raise LisaException(f"Kernel file {kernel} doesn't exist.")

        if kernel.endswith(".tar.xz"):
            # extract kernel file
            self._log.debug(f"Extracting kernel package: {kernel}")
            target_path = self.node.get_str_path(self.node.working_path / "kernel")
            tar = self.node.tools[Tar]
            # some links cannot be extracted correctly in Windows, ignore error.
            tar.extract(file=kernel, dest_dir=target_path, raise_error=False)
            kernel = target_path

        ls = self.node.tools[Ls]
        if not ls.is_file(self.node.get_pure_path(kernel)):
            # looking for kernel files in the dir
            find = self.node.tools[Find]
            files = find.find_files(
                start_path=self.node.get_pure_path(kernel), name_pattern="vmlinux-*"
            )
            assert_that(files).described_as(
                "expected to find exact one kernel file"
            ).is_length(1)
            kernel = files[0]

        self._log.debug(f"Used kernel file: {kernel}")
        # replace \ to \\ for the path in .wslconfig
        kernel = kernel.replace("\\", "\\\\")

        return kernel
