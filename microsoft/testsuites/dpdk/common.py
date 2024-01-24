# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from datetime import datetime
from typing import Any, Dict

from assertpy import assert_that

from lisa import Node
from lisa.operating_system import Debian, Oracle, Redhat, Suse, Ubuntu
from lisa.util import UnsupportedDistroException

DPDK_STABLE_GIT_REPO = "https://dpdk.org/git/dpdk-stable"

# azure routing table magic subnet prefix
# signals 'route all traffic on this subnet'
AZ_ROUTE_ALL_TRAFFIC = "0.0.0.0/0"


def force_dpdk_default_source(variables: Dict[str, Any]) -> None:
    if not variables.get("dpdk_source", None):
        variables["dpdk_source"] = DPDK_STABLE_GIT_REPO


# rough check for ubuntu supported versions.
# assumes:
# - canonical convention of YEAR.MONTH for major versions
# - canoical release cycle of EVEN_YEAR.04 for lts versions.
# - 4 year support cycle. 6 year for ESM
# get the age of the distro, if negative or 0, release is new.
# if > 6, distro is out of support
def is_ubuntu_lts_version(distro: Ubuntu) -> bool:
    # asserts if not ubuntu OS object
    version_info = distro.information.version
    distro_age = _get_ubuntu_distro_age(distro)
    is_even_year = (version_info.major % 2) == 0
    is_april_release = version_info.minor == 4
    is_within_support_window = distro_age <= 6
    return is_even_year and is_april_release and is_within_support_window


def is_ubuntu_latest_or_prerelease(distro: Ubuntu) -> bool:
    distro_age = _get_ubuntu_distro_age(distro)
    return distro_age <= 2


def _get_ubuntu_distro_age(distro: Ubuntu) -> int:
    version_info = distro.information.version
    # check release is within esm window
    year_string = str(datetime.today().year)
    assert_that(len(year_string)).described_as(
        "Package bug: The year received from datetime module is an "
        "unexpected size. This indicates a broken package or incorrect "
        "date in this computer."
    ).is_greater_than_or_equal_to(4)
    # TODO: handle the century rollover edge case in 2099
    current_year = int(year_string[-2:])
    release_year = int(version_info.major)
    # 23-18 == 5
    # long term support and extended security updates for ~6 years
    return current_year - release_year


def check_dpdk_support(node: Node) -> None:
    # check requirements according to:
    # https://docs.microsoft.com/en-us/azure/virtual-network/setup-dpdk
    supported = False
    if isinstance(node.os, Debian):
        if isinstance(node.os, Ubuntu):
            node.log.debug(
                "Checking Ubuntu release: "
                f"is_latest_or_prerelease? ({is_ubuntu_latest_or_prerelease(node.os)})"
                f" is_lts_version? ({is_ubuntu_lts_version(node.os)})"
            )
            # TODO: undo special casing for 18.04 when it's usage is less common
            supported = (
                node.os.information.version == "18.4.0"
                or is_ubuntu_latest_or_prerelease(node.os)
                or is_ubuntu_lts_version(node.os)
            )
        else:
            supported = node.os.information.version >= "11.0.0"
    elif isinstance(node.os, Redhat) and not isinstance(node.os, Oracle):
        supported = node.os.information.version >= "7.5.0"
    elif isinstance(node.os, Suse):
        supported = node.os.information.version >= "15.0.0"
    else:
        # this OS is not supported
        raise UnsupportedDistroException(
            node.os, "This OS is not supported by the DPDK test suite for Azure."
        )

    if not supported:
        raise UnsupportedDistroException(
            node.os, "This OS version is EOL and is not supported for DPDK on Azure"
        )
