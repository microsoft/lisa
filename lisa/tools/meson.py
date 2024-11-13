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
    @property
    def command(self) -> str:
        return "meson"

    def _check_exists(self) -> bool:
        result = self.node.execute("meson --version", shell=True)
        return result.exit_code == 0 and VersionInfo.parse(result.stdout) >= "0.52.0"

    @property
    def can_install(self) -> bool:
        return self.node.is_posix

    def _install(self) -> bool:
        posix_os: Posix = cast(Posix, self.node.os)
        # use pip to make sure we install a recent version
        if (not posix_os.package_exists("meson")) or posix_os.get_package_information(
            "meson", use_cached=False
        ) < "0.52.0":
            username = self.node.tools[Whoami].get_username()
            self.node.tools[Pip].install_packages("meson", install_to_user=True)
            # environment variables won't expand even when using shell=True :\
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
