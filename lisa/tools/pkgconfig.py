# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

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

    def package_info_exists(self, package_name: str) -> bool:
        package_info_result = self.run(f"--modversion {package_name}", force_run=True)
        return package_info_result.exit_code == 0

    def get_package_info(
        self,
        package_name: str,
        update_cached: bool = False,
    ) -> str:
        info_exists = self.package_info_exists(package_name=package_name)
        assert_that(info_exists).described_as(
            (
                f"pkg-config information was not available for {package_name}. "
                "This indicates an installation or package detection bug. "
                f"ensure .pc file is available for {package_name} on this OS."
            )
        ).is_true()
        return self.run(f"--modversion {package_name}", shell=True).stdout

    def get_package_version(
        self, package_name: str, update_cached: bool = False
    ) -> VersionInfo:
        version_info = self.get_package_info(package_name, update_cached=update_cached)
        return parse_version(version_info)
