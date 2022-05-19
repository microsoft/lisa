# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import string
from pathlib import Path, PurePath
from typing import List, Type, cast

from lisa.executable import Tool
from lisa.operating_system import Posix
from lisa.tools import Git, Make


class KvmUnitTests(Tool):
    # These tests take some time to finish executing. The default
    # timeout of 600 is not sufficient.
    TIME_OUT = 1200

    test_runner_cmd: str = ""
    repo_root: PurePath

    repo = "https://gitlab.com/kvm-unit-tests/kvm-unit-tests.git"
    deps = [
        "gcc",
        "make",
        "binutils",
        "qemu-kvm",
    ]

    @property
    def command(self) -> str:
        return str(self.test_runner_cmd)

    @property
    def can_install(self) -> bool:
        return True

    @property
    def dependencies(self) -> List[Type[Tool]]:
        return [Git, Make]

    @property
    def exists(self) -> bool:
        return True if self.test_runner_cmd else False

    def run_tests(self) -> List[str]:
        result = self.run(
            "",
            timeout=self.TIME_OUT,
            sudo=True,
            force_run=True,
            cwd=self.repo_root,
            no_info_log=False,  # print out result of each test
        )

        lines = result.stdout.split("\n")
        failures: List[str] = []
        for line in lines:
            line = "".join(filter(lambda c: c in string.printable, line))
            if "FAIL" in line:
                test_name = line.split(" ")[1]
                failures.append(test_name)
        return failures

    def save_logs(self, test_names: List[str], log_path: Path) -> None:
        for test_name in test_names:
            self.node.shell.copy_back(
                self.repo_root / "logs" / f"{test_name}.log",
                log_path / f"{test_name}.failure.log",
            )

    def _install_dep(self) -> None:
        posix_os: Posix = cast(Posix, self.node.os)
        tool_path = self.get_tool_path()
        git = self.node.tools[Git]
        git.clone(self.repo, tool_path)

        # install dependency packages
        for package in list(self.deps):
            if posix_os.is_package_in_repo(package):
                posix_os.install_packages(package)

    def _install(self) -> bool:
        self._log.info("Building kvm-unit-tests")
        self._install_dep()
        tool_path = self.get_tool_path()
        make = self.node.tools[Make]
        self.repo_root = tool_path.joinpath("kvm-unit-tests")

        # run ./configure in the repo
        configure_path = self.repo_root.joinpath("configure")
        self.node.execute(str(configure_path), cwd=self.repo_root, expected_exit_code=0)

        # run make in the repo
        make.make("", self.repo_root)

        self.test_runner_cmd = str(self.repo_root.joinpath("run_tests.sh"))
        self._log.info("Finished building kvm-unit-tests")
        return True
