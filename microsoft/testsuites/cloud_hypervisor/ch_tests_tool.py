# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
import string
from pathlib import Path, PurePath
from typing import Any, List, Type, cast

from lisa.executable import Tool
from lisa.operating_system import CBLMariner, Posix
from lisa.tools import Git, Docker, Modprobe

class CloudHypervisorTests(Tool):
    TIME_OUT = 3600
    
    repo = "https://github.com/cloud-hypervisor/cloud-hypervisor.git"

    cmd_path: PurePath
    repo_root: PurePath

    @property
    def command(self) -> str:
        return str(self.cmd_path)

    @property
    def can_install(self) -> bool:
        return True

    @property
    def dependencies(self) -> List[Type[Tool]]:
        return [Git, Docker]

    def run_tests(self, test_type: str, exclude: List[str] = []) -> None:
        self.node.tools[Modprobe].load("openvswitch")
        self.node.tools[Docker].start()

        skip_args = ' '.join(map(lambda t: f"--skip {t}", excluded_tests))
        result = self.run(
            f"tests --{test_type} -- -- {skip_args}",
            timeout=self.TIME_OUT,
            force_run=True,
            cwd=self.repo_root,
            no_info_log=False,  # print out result of each test
            # expected_exit_code=0,
        )

        return self._extract_failed_tests(result.stdout);
        
    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        tool_path = self.get_tool_path(use_global=True)
        self.repo_root = tool_path / "cloud-hypervisor"
        self.cmd_path = self.repo_root / "scripts" / "dev_cli.sh"
        print(str(self.cmd_path))
 
    def _install(self) -> bool:
        git = self.node.tools[Git]
        git.clone(self.repo, self.get_tool_path(use_global=True))
        if isinstance(self.node.os, CBLMariner):
            daemon_json_file = "/etc/docker/daemon.json"
            daemon_json = '{"default-ulimits":{"nofile":{"Hard":65535,"Name":"nofile","Soft":65535}}}'
            self.node.execute(
                f"echo '{daemon_json}' | sudo tee {daemon_json_file}",
                shell=True,sudo=True
            )

        return self._check_exists()

    def _extract_failed_tests(self, output: str) -> List[str]:
        lines = output.split('\n')
        failures = []
        found_failures = False
        failure_re = re.compile("\\s+(\\S+)")
        for line in lines:
            if line.startswith("failures:"):
                found_failures = True
                continue

            if found_failures:
                matches = failure_re.match(line)
                if matches is None:
                    found_failures = False
                    continue
                failures.append(matches.group(1))
        print(failures)
        return failures

