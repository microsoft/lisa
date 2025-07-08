# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import cast

from lisa.executable import Tool
from lisa.operating_system import CBLMariner, Posix
from lisa.util.process import Process

from .git import Git
from .make import Make
from lisa.util.logger import Logger


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
        
        # First check if the repository already has the version we want
        if self._repo_has_required_version():
            # Repository has V0.14.01, use it directly
            #add log to check we are in this function
            
            #log.info("Using existing repository version of stress-ng")
            posix_os.add_repository("ppa:colin-king/stress-ng")
            posix_os.update_packages()
            posix_os.install_packages("stress-ng")
            #posix_os.install_packages("stress-ng")
        else:
            # Repository doesn't have V0.14.01, try Colin King's PPA
            try:
                #log.info("inside else Using existing repository version of stress-ng")
                posix_os.add_repository("ppa:colin-king/stress-ng")
                posix_os.update_packages()
                posix_os.install_packages("stress-ng")
                
            except Exception:
                # PPA failed, fallback to whatever is available
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
        cmd = ""
        if num_workers:
            cmd += f" --vm {num_workers} "
        if num_workers:
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

    def launch_job_async(
        self, job_file: str, sudo: bool = False, quiet_brief: bool = False
    ) -> Process:
        """
        Launch stress-ng job asynchronously using a job file.

        Args:
            job_file: Path to the stress-ng job file
            sudo: Execute with elevated privileges
            quiet_brief: Enable quiet brief mode to reduce output verbosity

        Returns:
            Process: Asynchronous process handle for the stress-ng job
        """
        qb_flag = "--quiet-brief" if quiet_brief else ""
        return self.run_async(f"{qb_flag} --job {job_file}", force_run=True, sudo=sudo)

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

    def _repo_has_required_version(self) -> bool:
        """Check if the repository has stress-ng version V0.14.01"""
        try:
            # Check what version is available in the repository
            result = self.node.execute("apt-cache policy stress-ng", shell=True)
            #log.info(f"apt-cache policy output: {result.stdout}")
            # Look for the candidate version in the output
            # Example output: "Candidate: 0.11.23-1ubuntu1"
            for line in result.stdout.split('\n'):
                if 'Candidate:' in line and '0.14.01' in line:
                    return True
            
            # Also check the version table
            # Example: "     0.11.23-1ubuntu1 500"
            for line in result.stdout.split('\n'):
                if '0.14.01' in line and ('500' in line or '100' in line):
                    return True
                    
            return False
        except Exception:
            return False
