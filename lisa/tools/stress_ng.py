# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import cast

from lisa.executable import Tool
from lisa.operating_system import CBLMariner, Posix
from lisa.util.process import Process

from .git import Git
from .make import Make


class StressNg(Tool):
    repo = "https://github.com/ColinIanKing/stress-ng"
    branch = "V0.14.01"

    @property
    def command(self) -> str:
        return "stress-ng"

    @property
    def can_install(self) -> bool:
        return True

    def install(self) -> bool:
        posix_os: Posix = cast(Posix, self.node.os)
        if posix_os.is_package_in_repo("stress-ng"):
            posix_os.install_packages("stress-ng")
        else:
            self._install_from_src()
        return self._check_exists()

    def launch_vm_stressor(
        self, num_workers: int = 0, vm_bytes: str = "", timeout_in_seconds: int = 0
    ) -> None:
        # --vm N, start N workers spinning on anonymous mmap
        # --timeout T, timeout after T seconds
        # --vm-bytes N, allocate N bytes per vm worker
        #  (default 256MB)
        cmd = " --vm-keep "
        if num_workers:
            cmd += f" --vm {num_workers} "
        if vm_bytes:
            cmd += f" --vm-bytes {vm_bytes} "
        if timeout_in_seconds:
            cmd += f" --timeout {timeout_in_seconds} "
        self.run(cmd, force_run=True)

    def launch_cpu(self, num_cores: int = 0, timeout_in_seconds: int = 3600) -> None:
        # --cpu N, start N CPU workers
        # --timeout T, timeout after T seconds
        cmd = ""
        if num_cores:
            cmd += f" --cpu {num_cores} "

        cmd += f" --timeout {timeout_in_seconds} "
        self.run(cmd, force_run=True, timeout=timeout_in_seconds)

    def launch_job_async(self, job_file: str, sudo: bool = False) -> Process:
        return self.run_async(f"--job {job_file}", force_run=True, sudo=sudo)

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
            self.node.os.install_packages(["glibc-devel", "kernel-headers", "binutils"])

    def _install_from_src(self) -> bool:
        tool_path = self.get_tool_path()
        git = self.node.tools[Git]
        git.clone(self.repo, tool_path, ref=self.branch)

        make = self.node.tools[Make]
        self._install_required_packages()
        code_path = tool_path.joinpath("stress-ng")
        make.make_install(cwd=code_path)
        return self._check_exists()
