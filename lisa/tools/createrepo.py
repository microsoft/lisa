# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.


from pathlib import Path

from lisa.executable import Tool
from lisa.operating_system import CBLMariner
from lisa.tools.tar import Tar
from lisa.tools.tee import Tee
from lisa.util import UnsupportedDistroException


class CreateRepo(Tool):
    @property
    def command(self) -> str:
        return "createrepo"

    @property
    def can_install(self) -> bool:
        return True

    def _install(self) -> bool:
        if isinstance(self.node.os, CBLMariner):
            self.node.os.install_packages("createrepo")
        else:
            raise UnsupportedDistroException(
                self.node.os,
                f"tool {self.command} can't be installed in {self.node.os.name}",
            )
        return self._check_exists()

    def create_repo_from_tarball(self, tarball_path: Path) -> None:
        workspace = Path(self.node.get_working_path())
        repo_path = workspace / "rpms"

        # extract tarball
        self.node.tools[Tar].extract(
            file=tarball_path.as_posix(),
            dest_dir=repo_path.as_posix(),
        )

        # run createrepo
        self._run_create_repo(path=repo_path.as_posix(), compatibility=True)

        # add repo file
        repo_file = "[builtpackages]\n"
        repo_file += "name=Built Packages\n"
        repo_file += f"baseurl=file://{repo_path.as_posix()}\n"  # noqa: E231
        repo_file += "enabled=1\n"
        repo_file += "gpgcheck=0\n"
        repo_file += "priority=1\n"
        repo_file += "skip_if_unavailable=True\n"

        # write repo file to /etc/yum/repos.d/
        repo_file_path = Path("/etc/yum.repos.d/builtpackages.repo")
        self.node.tools[Tee].write_to_file(repo_file, repo_file_path, sudo=True)

    def _run_create_repo(self, path: str, compatibility: bool = True) -> None:
        cmd = path
        if compatibility:
            cmd = f"--compatibility {cmd}"
        self.run(
            cmd,
            expected_exit_code=0,
            expected_exit_code_failure_message="Failed to create repository",
            shell=True,
            sudo=False,
            force_run=True,
        )
