# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
from pathlib import PurePath
from typing import Any, List, Optional, Type

from lisa.executable import Tool
from lisa.operating_system import CBLMariner
from lisa.tools import Docker, Echo, Git, Whoami


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

    def run_tests(self, test_type: str, skip: Optional[List[str]] = None) -> List[str]:
        if skip is not None:
            skip_args = " ".join(map(lambda t: f"--skip {t}", skip))
        else:
            skip_args = ""

        result = self.run(
            f"tests --{test_type} -- -- {skip_args}",
            timeout=self.TIME_OUT,
            force_run=True,
            cwd=self.repo_root,
            no_info_log=False,  # print out result of each test
            shell=True,
        )

        failures = self._extract_failed_tests(result.stdout)
        if not failures:
            result.assert_exit_code()

        return failures

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        tool_path = self.get_tool_path(use_global=True)
        self.repo_root = tool_path / "cloud-hypervisor"
        self.cmd_path = self.repo_root / "scripts" / "dev_cli.sh"

    def _install(self) -> bool:
        git = self.node.tools[Git]
        git.clone(self.repo, self.get_tool_path(use_global=True))
        if isinstance(self.node.os, CBLMariner):
            daemon_json_file = PurePath("/etc/docker/daemon.json")
            daemon_json = '{"default-ulimits":{"nofile":{"Hard":65535,"Name":"nofile","Soft":65535}}}'  # noqa: E501
            self.node.tools[Echo].write_to_file(
                daemon_json, daemon_json_file, sudo=True
            )

        self.node.execute("groupadd -f docker")
        username = self.node.tools[Whoami].get_username()
        res = self.node.execute("getent group docker", expected_exit_code=0)
        if username not in res.stdout:  # if current user is not in docker group
            self.node.execute(f"usermod -a -G docker {username}", sudo=True)
            # reboot for group membership change to take effect
            self.node.reboot()

        self.node.tools[Docker].start()

        return self._check_exists()

    def _extract_failed_tests(self, output: str) -> List[str]:
        # The failures list is output by the test runner in this format:
        #
        # failures:
        #     failed_test_name_1
        #     failed_test_name_2
        #     ... so on
        #
        # To parse, we first find the "failures:" line and then parse the
        # following lines that begin with one or more whitespaces to extract
        # the test name.
        lines = output.split("\n")
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
        return failures
