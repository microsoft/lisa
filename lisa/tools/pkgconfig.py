# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Optional

from assertpy import assert_that
from semver import VersionInfo

from lisa.executable import Tool
from lisa.operating_system import Posix
from lisa.util import parse_version


class Pkgconfig(Tool):
    @property
    def command(self) -> str:
        return "pkg-config"

    @property
    def can_install(self) -> bool:
        return True

    def install(self) -> bool:
        assert isinstance(self.node.os, Posix)
        self.node.os.install_packages("pkg-config")
        return True

    def package_info_exists(
        self, package_name: str, pkg_config_path: Optional[str] = None
    ) -> bool:
        if pkg_config_path:
            update_env = {"PKG_CONFIG_PATH": f"{pkg_config_path}"}
        else:
            update_env = None
        package_info_result = self.run(
            f"--modversion {package_name}",
            force_run=True,
            shell=True,
            update_envs=update_env,
        )
        return package_info_result.exit_code == 0

    def get_package_info(
        self,
        package_name: str,
        update_cached: bool = False,
        pkg_config_path: Optional[str] = None,
    ) -> str:
        info_exists = self.package_info_exists(
            package_name=package_name, pkg_config_path=pkg_config_path
        )
        if pkg_config_path:
            update_env = {"PKG_CONFIG_PATH": f"{pkg_config_path}"}
        else:
            update_env = None
        assert_that(info_exists).described_as(
            (
                f"pkg-config information was not available for {package_name}. "
                "This indicates an installation or package detection bug. "
                f"ensure .pc file is available for {package_name} on this OS."
            )
        ).is_true()
        return self.run(
            f"--modversion {package_name}", shell=True, update_envs=update_env
        ).stdout

    def get_package_version(
        self,
        package_name: str,
        update_cached: bool = False,
        pkg_config_path: Optional[str] = None,
    ) -> VersionInfo:
        version_info = self.get_package_info(
            package_name, update_cached=update_cached, pkg_config_path=pkg_config_path
        )
        return parse_version(version_info)
