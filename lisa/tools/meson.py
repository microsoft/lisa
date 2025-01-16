# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import PurePath
from typing import cast

from semver import VersionInfo

from lisa.executable import Tool
from lisa.operating_system import Posix

from .ln import Ln
from .python import Pip
from .whoami import Whoami


class Meson(Tool):
    _minimum_version = "0.52.0"

    @property
    def command(self) -> str:
        return "meson"

    def _check_exists(self) -> bool:
        result = self.node.execute("meson --version", shell=True)
        return (
            result.exit_code == 0
            and VersionInfo.parse(result.stdout) >= self._minimum_version
        )

    @property
    def can_install(self) -> bool:
        return self.node.is_posix

    def _install(self) -> bool:
        posix_os: Posix = cast(Posix, self.node.os)
        # use pip to make sure we install a recent version

        package_installed = ""
        package_available = ""
        # packaged as 'meson' on older systems and 'python3-meson' on newer ones,
        # since it's actually just a python package.
        # So check for both
        for pkg in [
            "python3-meson",
            "meson",
        ]:
            if (
                posix_os.package_exists(pkg)
                and posix_os.get_package_information(pkg, use_cached=False)
                >= self._minimum_version
            ):
                package_installed = pkg
                break
            elif posix_os.is_package_in_repo(pkg):
                package_available = pkg
                break

        # prefer the packaged version as long as it's the right version
        if package_installed:
            return self._check_exists()
        if package_available:
            posix_os.install_packages(package_available)
            # verify version is correct if it's installed from pkg manager
            if posix_os.get_package_information(pkg) < self._minimum_version:
                posix_os.uninstall_packages(pkg)
                package_available = ""

        # otherwise, install with pip
        # this can get weird on some systems since they have started
        # returning an error code if you try to use pip without a venv
        if not (package_available or package_installed):
            username = self.node.tools[Whoami].get_username()
            self.node.tools[Pip].install_packages("meson", install_to_user=True)
            self.node.tools[Ln].create_link(
                f"/home/{username}/.local/bin/meson", "/usr/bin/meson", force=True
            )
            # ensure sudo has access as well
            self.node.execute(
                "pip3 install meson",
                sudo=True,
                shell=True,
                no_debug_log=True,
                no_info_log=True,
                no_error_log=True,
            )

        return self._check_exists()

    def setup(self, args: str, cwd: PurePath, build_dir: str = "build") -> PurePath:
        self.run(
            f"{args} {build_dir}",
            force_run=True,
            shell=True,
            cwd=cwd,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                f"Could not configure {str(cwd)} with meson using args {args}"
            ),
        )
        return cwd.joinpath(build_dir)
