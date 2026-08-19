# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import Path
from typing import cast

from lisa.executable import Tool
from lisa.operating_system import CBLMariner, Debian, Posix
from lisa.util import LisaException, RepoNotExistException, parse_version
from lisa.util.process import Process

from .git import Git
from .make import Make


class StressNg(Tool):
    repo = "https://github.com/ColinIanKing/stress-ng"
    # V0.22.00 is the first release that validates AVX-512 CPU features before
    # selecting target-cloned code, avoiding SIGILL on virtualized CPUs.
    branch = "V0.22.00"
    _minimum_safe_version = parse_version("0.22.0")

    @property
    def command(self) -> str:
        return "stress-ng"

    @property
    def can_install(self) -> bool:
        return True

    def _check_exists(self) -> bool:
        if not super()._check_exists():
            return False

        result = self.node.execute(
            f"{self.command} --version",
            shell=True,
            sudo=self._use_sudo,
            no_error_log=True,
            no_info_log=True,
        )
        if result.exit_code != 0:
            return False

        version_output = result.stdout.strip().removeprefix("stress-ng, version ")
        try:
            installed_version = parse_version(version_output.partition(" ")[0])
        except LisaException:
            self._log.debug(
                f"could not parse the installed {self.command} version; "
                "installing a fixed build from source"
            )
            return False

        if installed_version < self._minimum_safe_version:
            self._log.debug(
                f"installed {self.command} version is older than "
                f"{self.branch}; installing a fixed build from source"
            )
            return False
        return True

    def install(self) -> bool:
        posix_os: Posix = cast(Posix, self.node.os)
        if posix_os.is_package_in_repo(self.command):
            try:
                posix_os.install_packages(self.command)
            except RepoNotExistException:
                raise
            except LisaException as package_error:
                self._log.debug(
                    f"failed to install {self.command} from package manager: "
                    f"{package_error}"
                )

        if not self._check_exists():
            return self._install_from_src()
        return True

    def launch_vm_stressor(
        self, num_workers: int = 0, vm_bytes: str = "", timeout_in_seconds: int = 0
    ) -> None:
        # --vm N, start N workers spinning on anonymous mmap
        # --timeout T, timeout after T seconds
        # --vm-bytes N, allocate N bytes per vm worker
        #  (default 256MB)
        cmd = ""
        if num_workers:
            cmd += f" --vm {num_workers} "
        if num_workers:
            cmd += f" --vm-bytes {vm_bytes} "
        if timeout_in_seconds:
            cmd += f" --timeout {timeout_in_seconds} "
        self.run(cmd, force_run=True)

    def launch_mmaphuge_stressor_async(
        self, num_workers: int = 0, mmap_bytes: str = "", timeout_in_seconds: int = 0
    ) -> Process:
        # --mmaphuge N, start N workers stressing mmap with huge mappings
        # --mmaphuge-bytes N, mmap and munmap N bytes for each stress iteration
        # --timeout T, timeout after T seconds
        cmd = ""
        if num_workers:
            cmd += f" --mmaphuge {num_workers} "
        if mmap_bytes:
            cmd += f" --mmap-bytes {mmap_bytes} "
        if timeout_in_seconds:
            cmd += f" --timeout {timeout_in_seconds} "
        return self.run_async(cmd, force_run=True)

    def launch_cpu(self, num_cores: int = 0, timeout_in_seconds: int = 3600) -> None:
        # --cpu N, start N CPU workers
        # --timeout T, timeout after T seconds
        cmd = ""
        if num_cores:
            cmd += f" --cpu {num_cores} "

        cmd += f" --timeout {timeout_in_seconds} "
        self.run(cmd, force_run=True, timeout=timeout_in_seconds)

    def launch_job_async(self, job_file: str, sudo: bool = False) -> Process:
        job_cmd = f"--job {job_file}"
        # filename without extension
        job_filename = Path(job_file).stem
        yaml_output_name = f"{job_filename}.yaml"
        # Create full path to YAML file in working directory
        yaml_output_path = self.node.working_path / yaml_output_name
        job_cmd += f" --yaml {yaml_output_path}"

        return self.run_async(job_cmd, force_run=True, sudo=sudo)

    def launch_class_async(
        self,
        class_name: str,
        num_workers: int = 0,
        timeout_secs: int = 60,
        verbose: bool = True,
        sudo: bool = False,
    ) -> Process:
        v_flag = "-v" if verbose else ""
        return self.run_async(
            f"{v_flag} --sequential {num_workers} --class {class_name} "
            f"--timeout {timeout_secs}",
            sudo=sudo,
        )

    def _install_required_packages(self) -> None:
        if isinstance(self.node.os, CBLMariner):
            self.node.os.install_packages(
                [
                    "gcc",
                    "glibc-devel",
                    "kernel-headers",
                    "binutils",
                    "make",
                    "libapparmor-devel",
                ]
            )
        elif isinstance(self.node.os, Debian):
            self.node.os.install_packages("libapparmor-dev")

    def _install_from_src(self) -> bool:
        tool_path = self.get_tool_path()
        git = self.node.tools[Git]
        git.clone(self.repo, tool_path, ref=self.branch, shallow=True)

        make = self.node.tools[Make]
        self._install_required_packages()
        code_path = tool_path.joinpath("stress-ng")
        make.make_install(cwd=code_path)
        return self._check_exists()
