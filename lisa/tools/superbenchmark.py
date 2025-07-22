# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Optional, cast

from lisa.executable import Tool
from lisa.operating_system import Posix
from lisa.util import LisaException
from lisa.util.process import Process


class SuperBenchmark(Tool):
    """
    SuperBenchmark tool for AI infrastructure benchmarking.
    
    SuperBench is a validation and profiling tool for AI infrastructure,
    providing hardware and software benchmarks for AI systems.
    
    More information: https://github.com/microsoft/superbenchmark
    """

    @property
    def command(self) -> str:
        return "sb"

    @property
    def can_install(self) -> bool:
        return True

    def install(self) -> bool:
        """Install superbenchmark from source."""
        posix_os: Posix = cast(Posix, self.node.os)
        
        # First check if it's already installed
        if self._check_exists():
            return True
        
        # Clone superbenchmark repository
        from .git import Git
        from .make import Make
        
        git = self.node.tools[Git]
        tool_path = self.get_tool_path()
        
        try:
            # Clone the repository
            git.clone(
                "https://github.com/microsoft/superbenchmark",
                tool_path,
                ref="main"
            )
            
            code_path = tool_path.joinpath("superbenchmark")
            
            # Install with pip
            result = self.node.execute(
                "python3 -m pip install .",
                sudo=True,
                timeout=600,
                cwd=code_path
            )
            
            if result.exit_code != 0:
                self._log.debug(f"Failed to install superbench: {result.stderr}")
                return False
            
            # Run post-install if make is available
            make = self.node.tools[Make]
            if make.exists:
                make_result = make.run("postinstall", cwd=code_path, ignore_error=True)
                if make_result.exit_code != 0:
                    self._log.debug(f"Post-install step failed: {make_result.stderr}")
            
        except Exception as e:
            self._log.debug(f"Failed to install superbench from source: {e}")
            return False
            
        return self._check_exists()

    def run_benchmark(
        self,
        config_file: Optional[str] = None,
        docker_image: Optional[str] = None,
        mode: str = "local",
        output_dir: Optional[str] = None,
        timeout: int = 3600,
    ) -> Process:
        """
        Run superbenchmark benchmarks.
        
        Args:
            config_file: Path to configuration file
            docker_image: Docker image to use for benchmarks
            mode: Run mode (local, docker, etc.)
            output_dir: Output directory for results
            timeout: Timeout in seconds
            
        Returns:
            Process: The running process
        """
        cmd = "run"
        
        if config_file:
            cmd += f" --config-file {config_file}"
        if docker_image:
            cmd += f" --docker-image {docker_image}"
        if mode:
            cmd += f" --mode {mode}"
        if output_dir:
            cmd += f" --output-dir {output_dir}"
            
        return self.run_async(cmd, timeout=timeout, sudo=True)

    def generate_config(
        self,
        output_file: str = "superbench.yaml",
        template: Optional[str] = None,
    ) -> None:
        """
        Generate a configuration file for superbenchmark.
        
        Args:
            output_file: Output configuration file path
            template: Template to use for configuration
        """
        cmd = f"config --output {output_file}"
        
        if template:
            cmd += f" --template {template}"
            
        result = self.run(cmd, sudo=True)
        result.assert_exit_code()

    def get_version(self) -> str:
        """Get superbenchmark version."""
        result = self.run("version")
        result.assert_exit_code()
        return result.stdout.strip()

    def run_exec(
        self,
        benchmark_name: str,
        config_override: Optional[str] = None,
        timeout: int = 3600,
    ) -> Process:
        """
        Execute a specific benchmark directly.
        
        Args:
            benchmark_name: Name of the benchmark to execute
            config_override: Configuration overrides
            timeout: Timeout in seconds
            
        Returns:
            Process: The running process
        """
        cmd = f"exec --benchmark {benchmark_name}"
        
        if config_override:
            cmd += f" --config-override {config_override}"
            
        return self.run_async(cmd, timeout=timeout, sudo=True)

    def result_diagnosis(
        self,
        data_file: str,
        output_file: Optional[str] = None,
        baseline_file: Optional[str] = None,
    ) -> str:
        """
        Run result diagnosis on benchmark data.
        
        Args:
            data_file: Path to the benchmark data file
            output_file: Output file for diagnosis results
            baseline_file: Baseline file for comparison
            
        Returns:
            str: Diagnosis output
        """
        cmd = f"result diagnosis --data-file {data_file}"
        
        if output_file:
            cmd += f" --output-file {output_file}"
        if baseline_file:
            cmd += f" --baseline-file {baseline_file}"
            
        result = self.run(cmd, sudo=True)
        result.assert_exit_code()
        return result.stdout

    def validate_config(self, config_file: str) -> bool:
        """
        Validate a configuration file.
        
        Args:
            config_file: Path to configuration file to validate
            
        Returns:
            bool: True if valid, False otherwise
        """
        try:
            result = self.run(f"config --validate {config_file}")
            return result.exit_code == 0
        except LisaException:
            return False