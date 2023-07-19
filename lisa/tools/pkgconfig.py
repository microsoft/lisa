# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re

from assertpy import assert_that
from semver import VersionInfo

from lisa.executable import Tool
from lisa.operating_system import Posix

coerce_version_info_regex = re.compile(
    r"v?(?P<major>[0-9]+)\.(?P<minor>[0-9]+)(\.(?P<patch>[0-9]+))?"
)


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

    def _coerce_version_info_string(self, version_string: str) -> VersionInfo:
        if VersionInfo.isvalid(version_string):
            return VersionInfo.parse(version_string)
        # else, attempt to coerce
        matches = coerce_version_info_regex.search(version_string)
        assert (
            matches
        ), f"Could not coalesce version string {version_string} into a package version"

        major = matches.group("major")
        minor = matches.group("minor")
        patch = matches.group("patch")

        assert_that(major).described_as(
            f"Could not identify major version in version string {version_string}"
        ).is_not_none()
        assert_that(minor).described_as(
            f"Could not identify minor version in version string {version_string}"
        ).is_not_none()

        coerced_version = ".".join([str(int(x)) for x in [major, minor, patch]])
        return VersionInfo.parse(coerced_version)

    def get_package_info(
        self, package_name: str, check_exists: bool = False, update_cached: bool = False
    ) -> str:
        package_info_result = self.run(
            f"--modversion {package_name}", force_run=update_cached
        )
        if check_exists and package_info_result.exit_code != 0:
            return ""

        assert_that(package_info_result.exit_code).described_as(
            (
                f"pkg-config information was not available for {package_name}. "
                "This indicates an installation or package detection bug. "
                f"ensure .pc file is available for {package_name} on this OS."
            )
        ).is_zero()
        return package_info_result.stdout

    def get_package_version(
        self, package_name: str, update_cached: bool = False
    ) -> VersionInfo:
        version_info = self.get_package_info(package_name, update_cached=update_cached)
        return self._coerce_version_info_string(version_info)
