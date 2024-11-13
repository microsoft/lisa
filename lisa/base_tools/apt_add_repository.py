# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import TYPE_CHECKING

from lisa.executable import Tool

if TYPE_CHECKING:
    from lisa.operating_system import Ubuntu


class AptAddRepository(Tool):
    @property
    def command(self) -> str:
        return "apt-add-repository"

    @property
    def can_install(self) -> bool:
        return True

    def install(self) -> bool:
        ubuntu_os: Ubuntu = self.node.os  # type: ignore
        package_name = "software-properties-common"
        ubuntu_os.install_packages(package_name)
        return self._check_exists()

    def add_repository(self, repo: str) -> None:
        self.run(
            f'-y "{repo}"',
            sudo=True,
            force_run=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="fail to add repository",
        )

    def remove_repository(self, repo: str) -> None:
        self.run(
            f'--remove -y "{repo}"',
            sudo=True,
            force_run=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="fail to remove repository",
        )
