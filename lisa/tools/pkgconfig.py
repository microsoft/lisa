# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
from typing import Optional, Type, Union

import semver
from assertpy import assert_that, fail
from semver import VersionInfo

from lisa.executable import Tool
from lisa.operating_system import Debian, Fedora, Posix, Suse

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

    def package_info_exists(self, package_name: str) -> bool:
        return self.run(f"--modversion {package_name}").exit_code == 0

    def get_package_version(self, package_name: str) -> VersionInfo:
        assert_that(self.package_info_exists(package_name)).described_as(
            "pkg-config information was not available for DPDK. This indicates an installation or package detection bug in dpdktestpmd.py"
        ).is_true()
        version_string = self.run(f"--modversion {package_name}").stdout
        return self._coerce_version_info_string(version_string)
