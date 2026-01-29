# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import cast

from lisa.executable import Tool


class Dpkg(Tool):
    @property
    def command(self) -> str:
        return "dpkg"

    @property
    def can_install(self) -> bool:
        return True

    def install(self) -> bool:
        from lisa.operating_system import Posix

        posix_os: Posix = cast(Posix, self.node.os)
        package_name = "dpkg"
        posix_os.install_packages(package_name)
        return self._check_exists()

    def is_valid_package(self, file: str) -> bool:
        # Check if the file is a valid deb package
        result = self.run(
            f"--info {file}",
        )
        return result.exit_code == 0

    def install_local_package(self, file: str, force: bool = True) -> None:
        # Install a single deb package
        parameters = f"-i {file}"
        if force:
            parameters = f" --force-all {parameters}"
        self.run(
            parameters,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(f"failed to install {file}"),
        )
