# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import pathlib
import re
from typing import List

from lisa.executable import Tool
from lisa.operating_system import Posix
from lisa.util import LisaException, constants, filter_ansi_escape, get_matched_str


class CodeExistsException(LisaException):
    ...


class Git(Tool):
    CODE_FOLDER_PATTERN = re.compile(r"Cloning into '(.+)'")
    CODE_FOLDER_ON_EXISTS_PATTERN = re.compile(
        r"destination path '(?P<path>.*?)' already exists "
        r"and is not an empty directory.",
        re.M,
    )

    @property
    def command(self) -> str:
        return "git"

    @property
    def can_install(self) -> bool:
        return True

    def _install(self) -> bool:
        if isinstance(self.node.os, Posix):
            self.node.os.install_packages([self])
        else:
            raise LisaException(
                "Doesn't support to install git in Windows. "
                "Make sure git is installed and in PATH"
            )
        return self._check_exists()

    def clone(
        self,
        url: str,
        cwd: pathlib.PurePath,
        ref: str = "",
        dir_name: str = "",
        fail_on_exists: bool = True,
        recurse_submodules: bool = False,
    ) -> pathlib.PurePath:
        self.node.shell.mkdir(cwd, exist_ok=True)

        cmd = f"clone {url} {dir_name} --recurse-submodules"
        # git print to stderr for normal info, so set no_error_log to True.
        result = self.run(cmd, cwd=cwd, no_error_log=True)
        if result.exit_code == 0:
            output = result.stderr
            if not output:
                output = result.stdout
            code_dir = get_matched_str(output, self.CODE_FOLDER_PATTERN)
        else:
            stdout = result.stdout
            code_dir = get_matched_str(stdout, self.CODE_FOLDER_ON_EXISTS_PATTERN)
            if code_dir:
                if fail_on_exists:
                    raise CodeExistsException(f"code or folder exists. {stdout}")
                else:
                    self._log.debug(f"path '{code_dir}' exists, clone skipped.")
            else:
                raise LisaException(f"failed to clone the repo. {stdout}")
        full_path = cwd / code_dir
        self._log.debug(f"code path: {full_path}")
        if ref:
            self.checkout(ref, cwd=full_path)
        return full_path

    def checkout(
        self, ref: str, cwd: pathlib.PurePath, checkout_branch: str = ""
    ) -> None:
        if not checkout_branch:
            # create a temp branch to checkout tag or commit.
            checkout_branch = f"{constants.RUN_ID}"

        # force run to make sure checkout among branches correctly.
        result = self.run(
            f"checkout {ref} -b {checkout_branch}",
            force_run=True,
            cwd=cwd,
            no_info_log=True,
            no_error_log=True,
        )
        result.assert_exit_code(message=f"failed to checkout branch. {result.stdout}")

    def pull(self, cwd: pathlib.PurePath) -> None:
        result = self.run(
            "pull",
            force_run=True,
            cwd=cwd,
            no_info_log=True,
            no_error_log=True,
        )
        result.assert_exit_code(message=f"failed to pull code. {result.stdout}")

    def fetch(self, cwd: pathlib.PurePath) -> None:
        result = self.run(
            "fetch -p",
            force_run=True,
            cwd=cwd,
            no_info_log=True,
            no_error_log=True,
        )
        result.assert_exit_code(message=f"failed to fetch code. {result.stdout}")

    def apply(
        self,
        cwd: pathlib.PurePath,
        patches: pathlib.PurePath,
    ) -> None:
        result = self.run(
            f"apply {patches}",
            shell=True,
            cwd=cwd,
            force_run=True,
            no_info_log=True,
            no_error_log=True,
        )
        result.assert_exit_code(message=f"failed on applying patches. {result.stdout}")

    def list_tags(self, cwd: pathlib.PurePath) -> List[str]:
        result = self.run(
            "--no-pager tag --color=never",
            shell=True,
            cwd=cwd,
            expected_exit_code=0,
            expected_exit_code_failure_message="Could not fetch tags from git repo.",
        )
        return filter_ansi_escape(result.stdout).splitlines()

    def init_submodules(self, cwd: pathlib.PurePath) -> None:
        self.run(
            "submodule update --init",
            shell=True,
            cwd=cwd,
            expected_exit_code=0,
            expected_exit_code_failure_message="error on init submodules.",
        )
