# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import PurePath
from typing import cast

from semver import VersionInfo

from lisa.executable import Tool
from lisa.operating_system import Posix
from lisa.util import parse_version

from .ln import Ln
from .python import Pip
from .whoami import Whoami


class Meson(Tool):
    _minimum_version = parse_version("0.52.0")

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
        # But now we have a bunch of annoying cases.
        # 'meson' is installed but the wrong version
        # meson is installed but the right version
        # meson is not installed and it's the wrong version
        # meson is not installed and it's the right version
        for pkg in [
            "python3-meson",
            "meson",
        ]:
            if posix_os.package_exists(pkg):
                package_installed = pkg
                break
            elif posix_os.is_package_in_repo(pkg):
                package_available = pkg
                break

        # install the available package, if one was available and not installed
        if package_available:
            posix_os.install_packages(package_available)
            package_installed = package_available

        # now, if either previoulsy or newly installed package, check the version
        if package_installed:
            if (
                posix_os.get_package_information(package_installed, use_cached=False)
                < self._minimum_version
            ):
                # and uninstall if the version is not recent enough
                posix_os.uninstall_packages(package_installed)
                package_installed = ""
            else:
                # otherwise, we're done.
                return self._check_exists()

        # If we get here, we couldn't find a good version from the package manager
        # so we will install with pip. This is least desirable since it introduces
        # unpredictable behavior when running meson or ninja with sudo.
        # Like sudo ninja install, for example.
        if not package_installed:
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
