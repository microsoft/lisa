# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import pathlib
import re
from typing import Dict, List, Optional

from semver import VersionInfo

from lisa.executable import Tool
from lisa.operating_system import Posix, Suse
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
    CERTIFICATE_ISSUE_PATTERN = re.compile(
        r"server certificate verification failed", re.M
    )
    VERSION_PATTERN = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")

    @property
    def command(self) -> str:
        return "git"

    @property
    def can_install(self) -> bool:
        return True

    def _install(self) -> bool:
        if isinstance(self.node.os, Suse):
            self.node.os.install_packages("git-core")
        elif isinstance(self.node.os, Posix):
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
        auth_token: Optional[str] = None,
        timeout: int = 600,
    ) -> pathlib.PurePath:
        self.node.shell.mkdir(cwd, exist_ok=True)
        auth_flag = ""
        if auth_token:
            auth_flag = f'-c http.extraheader="AUTHORIZATION: bearer {auth_token}"'

        cmd = f"clone {auth_flag} {url} {dir_name} --recurse-submodules"

        # git print to stderr for normal info, so set no_error_log to True.
        result = self.run(cmd, cwd=cwd, no_error_log=True, timeout=timeout)
        if get_matched_str(result.stdout, self.CERTIFICATE_ISSUE_PATTERN):
            self.run("config --global http.sslverify false")
            result = self.run(
                cmd,
                cwd=cwd,
                no_error_log=True,
                force_run=True,
                timeout=timeout,
            )

        # mark directory safe
        self._mark_safe(cwd)

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
        self,
        ref: str,
        cwd: pathlib.PurePath,
        checkout_branch: str = "",
    ) -> None:
        delete_temp_branch = False
        if not checkout_branch:
            # create a temp branch to checkout tag or commit.
            checkout_branch = f"{constants.RUN_ID}"
            # check if this name is already in use
            branch_before_checkout = self.get_current_branch(cwd=cwd)
            if branch_before_checkout == checkout_branch:
                delete_temp_branch = True

        # mark directory safe
        self._mark_safe(cwd)
        branch_before_checkout = self.get_current_branch(cwd=cwd)
        # force run to make sure checkout among branches correctly.
        result = self.run(
            f"checkout {ref}",
            force_run=True,
            cwd=cwd,
            no_info_log=True,
            no_error_log=True,
        )

        if result.exit_code != 0:
            # Try fetching the ref and checking out FETCH_HEAD
            # This is sometimes necessary when checking out pull requests refs such as
            # refs/pull/1234/merge
            self._log.debug(f"Direct checkout of {ref} failed, trying fetch")
            self.run(
                f"fetch origin {ref}",  # assuming the default 'origin' remote
                force_run=True,
                cwd=cwd,
                no_info_log=True,
                no_error_log=True,
                expected_exit_code=0,
            )

            result = self.run(
                "checkout FETCH_HEAD",
                force_run=True,
                cwd=cwd,
                no_info_log=True,
                no_error_log=True,
                expected_exit_code=0,
            )

        # delete old temp branch before checking out new one
        if delete_temp_branch:
            self.run(
                f"branch -D {branch_before_checkout}",
                force_run=True,
                cwd=cwd,
                no_info_log=True,
                no_error_log=True,
            )
            result.assert_exit_code(
                message=f"failed to delete old temp branch. {result.stdout}"
            )

        # create temp branch
        result = self.run(
            f"checkout -b {checkout_branch}",
            force_run=True,
            cwd=cwd,
            no_info_log=True,
            no_error_log=True,
        )
        # to output the stdout to log, so it's not integrated with above line.
        result.assert_exit_code(message=f"failed to checkout branch. {result.stdout}")

        # in case there is submodule.
        self.run(
            "submodule update",
            force_run=True,
            cwd=cwd,
            no_info_log=True,
        )

    def discard_local_changes(self, cwd: pathlib.PurePath) -> None:
        result = self.run("checkout .", force_run=True, cwd=cwd, no_error_log=True)
        result.assert_exit_code(
            message=f"failed to discard local changes. {result.stdout}"
        )

    def pull(self, cwd: pathlib.PurePath) -> None:
        result = self.run(
            "pull",
            force_run=True,
            cwd=cwd,
            no_info_log=True,
            no_error_log=True,
        )
        result.assert_exit_code(message=f"failed to pull code. {result.stdout}")

    def fetch(self, cwd: pathlib.PurePath, remote: str = "") -> None:
        cmd = "fetch -p"
        if remote:
            cmd += f" {remote}"
        result = self.run(
            cmd,
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
        file_extension = patches.suffix
        if file_extension == ".mbx":
            result = self.run(
                f"am {patches}",
                shell=True,
                cwd=cwd,
                force_run=True,
                no_info_log=True,
                no_error_log=True,
            )
        else:
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

    def list_commit_ids(self, cwd: pathlib.PurePath) -> List[str]:
        result = self.run(
            "--no-pager log --pretty=format:%h",
            shell=True,
            cwd=cwd,
            force_run=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="Failed to fetch commit ids.",
        )
        return filter_ansi_escape(result.stdout).splitlines()

    def get_latest_commit_id(self, cwd: pathlib.PurePath) -> str:
        result = self.run(
            "--no-pager log -n 1 --pretty=format:%h",
            shell=True,
            cwd=cwd,
            force_run=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="Failed to fetch latest commit id.",
        )
        return filter_ansi_escape(result.stdout)

    def init_submodules(self, cwd: pathlib.PurePath) -> None:
        self.run(
            "submodule update --init",
            shell=True,
            cwd=cwd,
            expected_exit_code=0,
            expected_exit_code_failure_message="error on init submodules.",
        )

    def get_tag(
        self,
        cwd: pathlib.PurePath,
        sort_by: str = "v:refname",
        contains: str = "",
        return_last: bool = True,
        filter_: str = "",
        fail_on_not_found: bool = True,
    ) -> str:
        sort_arg = ""
        contains_arg = ""
        # git tag sort was not added until 2.36.1 in 2015
        # https://github.com/git/git/commit/b7cc53e92c806b73e14b03f60c17b7c29e52b4a4

        # git tag exposes various sort options, apply them if present
        # default is sort by version, ascending
        if sort_by:
            sort_arg = f"--sort={sort_by}"
        if contains:
            # git tag allows you to filter by a commit id, apply it is present.
            contains_arg = f"--contains {contains}"

        if self.get_version() >= VersionInfo.parse("2.36.1") or not sort_arg:
            git_cmd = f"--no-pager tag {sort_arg} {contains_arg}"
        else:
            # version is less than 2.36 and sorting is desired
            # ask git to list tags and sort with sort -V
            git_cmd = f" --no-pager tag -l {contains_arg} | sort -V"

        tags = self.run(
            git_cmd,
            cwd=cwd,
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "git tag failed to fetch tags, "
                "check sort and commit arguments are correct"
            ),
        ).stdout.splitlines()
        if filter_:
            filter_re = re.compile(filter_)
            tags = [x for x in tags if filter_re.search(x)]

        # build some nice error info for failure cases
        error_info = f"sortby:{sort_by} contains:{contains}"
        if filter_:
            error_info += f" filter:{filter_}"

        if len(tags) == 0:
            if fail_on_not_found:
                raise LisaException(
                    "Could not find any tags with this sort or "
                    f"filter setting: {error_info}"
                )
            else:
                self._log.debug(
                    "Could not find any tags with this sort or "
                    f"filter setting: {error_info}"
                )
                return ""

        if return_last:
            return tags[-1]
        else:
            return tags[0]

    def get_version(self) -> VersionInfo:
        result = self.run("--version")
        version_str = get_matched_str(result.stdout, self.VERSION_PATTERN)
        return VersionInfo.parse(version_str)

    def _mark_safe(self, cwd: pathlib.PurePath) -> None:
        self.run(f"config --global --add safe.directory {cwd}", cwd=cwd, force_run=True)

    def get_current_branch(self, cwd: pathlib.PurePath) -> str:
        result = self.run(
            "rev-parse --abbrev-ref HEAD",
            shell=True,
            cwd=cwd,
            force_run=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="Failed to fetch current branch.",
        )
        return filter_ansi_escape(result.stdout)

    def get_current_commit_hash(self, cwd: pathlib.PurePath) -> str:
        result = self.run("rev-parse HEAD", cwd=cwd, force_run=True, shell=True)
        result.assert_exit_code(
            message=f"failed getting current commit hash {result.stdout}"
        )
        return filter_ansi_escape(result.stdout)

    def get_repo_url(self, cwd: pathlib.PurePath, name: str = "origin") -> str:
        result = self.run(
            f"config --get remote.{name}.url",
            shell=True,
            cwd=cwd,
            force_run=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="Failed to fetch remote url.",
        )
        return filter_ansi_escape(result.stdout)

    def get_latest_commit_details(self, cwd: pathlib.PurePath) -> Dict[str, str]:
        result = dict()
        latest_commit_id = self.run(
            "--no-pager log -n 1 --pretty=format:%H",
            shell=True,
            cwd=cwd,
            force_run=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="Failed to fetch latest commit id.",
        ).stdout

        commit_message_name = self.run(
            "--no-pager log -n 1 --pretty=format:%B",
            shell=True,
            cwd=cwd,
            force_run=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="Failed to fetch latest commit message.",
        ).stdout

        author_email = self.run(
            "--no-pager log -n 1 --format='%ae'",
            shell=True,
            cwd=cwd,
            force_run=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="Failed to fetch author email.",
        ).stdout

        describe = self.run(
            "describe --always",
            shell=True,
            cwd=cwd,
            force_run=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="Failed to run git describe",
        ).stdout

        result = {
            "full_commit_id": filter_ansi_escape(latest_commit_id),
            "commit_message_name": filter_ansi_escape(commit_message_name),
            "contacts": filter_ansi_escape(author_email),
            "describe": filter_ansi_escape(describe),
        }

        return result

    def remote_list(self, cwd: pathlib.PurePath) -> List[str]:
        result = self.run(
            "remote",
            cwd=cwd,
            force_run=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="Failed to list remotes.",
        )
        remotes = filter_ansi_escape(result.stdout).strip()
        return remotes.splitlines()

    def remote_exists(self, cwd: pathlib.PurePath, name: str) -> bool:
        remotes = self.remote_list(cwd=cwd)
        return name in remotes

    def remote_add(
        self,
        cwd: pathlib.PurePath,
        name: str,
        url: str,
        fetch: bool = False,
    ) -> None:
        result = self.run(
            f"remote add {name} {url}",
            cwd=cwd,
            force_run=True,
            no_info_log=True,
            no_error_log=True,
        )
        result.assert_exit_code(
            message=f"failed to add remote '{name}' with url '{url}'.",
            include_output=True,
        )
        self._log.debug(f"added remote '{name}' -> {url}")

        if fetch:
            self.fetch(cwd=cwd, remote=name)

    def remote_remove(self, cwd: pathlib.PurePath, name: str) -> None:
        result = self.run(
            f"remote remove {name}",
            cwd=cwd,
            force_run=True,
            no_info_log=True,
            no_error_log=True,
        )
        result.assert_exit_code(
            message=f"failed to remove remote '{name}'.", include_output=True
        )
        self._log.debug(f"removed remote '{name}'")

    def remote_set_url(
        self,
        cwd: pathlib.PurePath,
        name: str,
        url: str,
        push: bool = False,
    ) -> None:
        cmd = "remote set-url"
        if push:
            cmd += " --push"

        cmd += f" {name} {url}"
        result = self.run(
            cmd,
            cwd=cwd,
            force_run=True,
            no_info_log=False,
        )
        result.assert_exit_code(
            message=f"failed to set url for remote '{name}'.", include_output=True
        )
        self._log.debug(f"set url for remote '{name}' -> {url}")

    def remote_get_url(
        self,
        cwd: pathlib.PurePath,
        name: str = "origin",
        push: bool = False,
    ) -> str:
        cmd = "remote get-url"
        if push:
            cmd += " --push"
        cmd += f" {name}"

        result = self.run(
            cmd,
            cwd=cwd,
            force_run=True,
            no_info_log=True,
            no_error_log=True,
        )
        result.assert_exit_code(
            message=f"failed to get url for remote {name}", include_output=True
        )
        return filter_ansi_escape(result.stdout).strip()

    def worktree_add(
        self,
        cwd: pathlib.PurePath,
        path: pathlib.PurePath,
        remote: str = "",
        remote_ref: str = "",
        new_branch: str = "",
        track: bool = False,
        detach: bool = False,
    ) -> pathlib.PurePath:
        self._mark_safe(cwd)

        cmd = "worktree add"

        if detach:
            cmd += " --detach"
        elif new_branch:
            if self.worktree_is_branch_checked_out(cwd, new_branch):
                # new_branch = f"{new_branch}_{constants.RUN_ID}"
                detach = True
                cmd += " --detach"
            else:
                if track:
                    cmd += " --track"
                cmd += f" -b {new_branch}"

        cmd += f" {path} "

        if remote:
            cmd += f"{remote}/"
        if remote_ref:
            cmd += f"{remote_ref}"

        result = self.run(
            cmd,
            cwd=cwd,
            no_info_log=True,
        )
        result.assert_exit_code(
            message=f"Failed to create worktree: {path}.", include_output=True
        )
        self._log.debug(f"created worktree at: {path}")
        self._mark_safe(path)
        return path

    def worktree_list(
        self,
        cwd: pathlib.PurePath,
    ) -> List[Dict[str, str]]:
        result = self.run(
            "worktree list --porcelain",
            cwd=cwd,
            force_run=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="Failed to list worktrees.",
        )

        worktrees: List[Dict[str, str]] = []
        current_worktree: Dict[str, str] = {}

        for line in filter_ansi_escape(result.stdout).splitlines():
            line = line.strip()
            if not line:
                if current_worktree:
                    worktrees.append(current_worktree)
                    current_worktree = {}
                continue

            if line.startswith("worktree "):
                current_worktree["path"] = line[len("worktree ") :]
            elif line.startswith("HEAD "):
                current_worktree["commit"] = line[len("HEAD ") :]
            elif line.startswith("branch "):
                current_worktree["branch"] = line[len("branch ") :]
            elif line == "detached":
                current_worktree["branch"] = "(detached)"
            elif line == "bare":
                current_worktree["branch"] = "(bare)"

        if current_worktree:
            worktrees.append(current_worktree)

        return worktrees

    def worktree_remove(
        self,
        cwd: pathlib.PurePath,
        path: pathlib.PurePath,
        force: bool = False,
    ) -> None:
        cmd = "worktree remove"
        if force:
            cmd += " --force"
        cmd += f" {path}"

        result = self.run(
            cmd,
            cwd=cwd,
            force_run=True,
            no_info_log=True,
            no_error_log=True,
        )
        result.assert_exit_code(
            message=f"failed to remove worktree at '{path}'.", include_output=True
        )
        self._log.debug(f"removed worktree at: {path}")

    def worktree_prune(
        self,
        cwd: pathlib.PurePath,
        dry_run: bool = False,
    ) -> str:
        cmd = "worktree prune"
        if dry_run:
            cmd += " --dry-run"

        result = self.run(
            cmd,
            cwd=cwd,
            force_run=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="Failed to prune worktrees.",
        )
        return filter_ansi_escape(result.stdout)

    def worktree_exists(self, cwd: pathlib.PurePath, path: str) -> bool:
        worktrees = self.worktree_list(cwd)
        return any(wt["path"] == path for wt in worktrees)

    def worktree_is_branch_checked_out(
        self,
        cwd: pathlib.PurePath,
        branch_name: str,
    ) -> bool:
        worktrees = self.worktree_list(cwd=cwd)

        # Normalize branch name - handle both "main" and "refs/heads/main"
        if not branch_name.startswith("refs/heads/"):
            full_branch_ref = f"refs/heads/{branch_name}"
        else:
            full_branch_ref = branch_name

        for wt in worktrees:
            wt_branch = wt["branch"]
            if wt_branch == full_branch_ref or wt_branch == branch_name:
                return True

        return False


class GitBisect(Git):
    _STOP_PATTERNS = ["first bad commit", "This means the bug has been fixed between"]

    @property
    def command(self) -> str:
        return "git bisect"

    def start(self, cwd: pathlib.PurePath) -> None:
        result = self.run("start", cwd=cwd, force_run=True)
        result.assert_exit_code(message=f"failed to start git bisect {result.stdout}")

    def good(self, cwd: pathlib.PurePath, ref: str = "") -> None:
        result = self.run(f"good {ref}", cwd=cwd, force_run=True)
        result.assert_exit_code(message=f"failed to run bisect good {result.stdout}")

    def bad(self, cwd: pathlib.PurePath, ref: str = "") -> None:
        result = self.run(f"bad {ref}", cwd=cwd, force_run=True)
        result.assert_exit_code(message=f"failed to run bisect bad {result.stdout}")

    def log(self, cwd: pathlib.PurePath) -> str:
        result = self.run("log", cwd=cwd, force_run=True)
        return result.stdout

    def check_bisect_complete(self, cwd: pathlib.PurePath) -> bool:
        result = self.log(cwd=cwd)
        if any(pattern in result for pattern in self._STOP_PATTERNS):
            return True
        return False
