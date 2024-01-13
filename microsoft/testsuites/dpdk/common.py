# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from datetime import datetime
from typing import Any, Dict

from assertpy import assert_that, fail

from lisa import Node
from lisa.operating_system import Debian, Oracle, Redhat, Suse, Ubuntu
from lisa.tools import Lscpu, Lspci
from lisa.util import UnsupportedDistroException
from lisa.util.constants import DEVICE_TYPE_SRIOV

DPDK_STABLE_GIT_REPO = "https://dpdk.org/git/dpdk-stable"

# azure routing table magic subnet prefix
# signals 'route all traffic on this subnet'
AZ_ROUTE_ALL_TRAFFIC = "0.0.0.0/0"


class DpdkVfHelper:
    MLX_CX3 = "mlx_cx3"
    MLX_CX4 = "mlx_cx4"
    MLX_CX5 = "mlx_cx5"
    MSFT_MANA = "mana"
    SINGLE_QUEUE = "single"
    MULTI_QUEUE = "multi"
    SEND = "send"
    RECV = "receive"
    FWD = "forwarder"
    NOT_SET = "not_set"

    # single queue is implemented but unused to avoid test bloat
    _dpdk_hw_l3fwd_gbps_thresholds = {
        MLX_CX3: {
            MULTI_QUEUE: {SEND: 20},
        },
        MLX_CX4: {
            MULTI_QUEUE: {FWD: 24},
        },
        MLX_CX5: {
            MULTI_QUEUE: {FWD: 28},
        },
        MSFT_MANA: {
            MULTI_QUEUE: {FWD: 170},
        },
    }

    _testpmd_thresholds = {
        MLX_CX3: {
            SINGLE_QUEUE: {SEND: 6_000_000, RECV: 5_000_000},
            MULTI_QUEUE: {SEND: 20_000_000, RECV: 17_000_000},
        },
        MLX_CX4: {
            SINGLE_QUEUE: {SEND: 7_000_000, RECV: 5_000_000},
            MULTI_QUEUE: {SEND: 25_000_000, RECV: 19_000_000},
        },
        MLX_CX5: {
            SINGLE_QUEUE: {SEND: 8_000_000, RECV: 6_000_000},
            MULTI_QUEUE: {SEND: 28_000_000, RECV: 24_000_000},
        },
        MSFT_MANA: {
            SINGLE_QUEUE: {SEND: 8_000_000, RECV: 6_000_000},
            MULTI_QUEUE: {SEND: 48_000_000, RECV: 45_000_000},
        },
    }

    def _set_network_hardware(self) -> None:
        lspci = self._node.tools[Lspci]
        device_list = lspci.get_devices_by_type(DEVICE_TYPE_SRIOV)
        is_connect_x3 = any(["ConnectX-3" in dev.device_info for dev in device_list])
        is_connect_x4 = any(["ConnectX-4" in dev.device_info for dev in device_list])
        is_connect_x5 = any(["ConnectX-5" in dev.device_info for dev in device_list])
        is_mana = any(["Microsoft" in dev.vendor for dev in device_list])
        if is_mana:
            self._hardware = self.MSFT_MANA
        elif is_connect_x3:
            self._hardware = self.MLX_CX3
        elif is_connect_x4:
            self._hardware = self.MLX_CX4
        elif is_connect_x5:
            self._hardware = self.MLX_CX5
        else:
            fail(
                "Test bug: unexpected network hardware! "
                "SRIOV is likely not enabled or this is a new, "
                "unimplemented bit of network hardware"
            )
        self._node.log.debug(f"Created threshold helper for nic: {self._hardware}")

    def __init__(self, should_enforce: bool, node: Node) -> None:
        self.use_strict_checks = should_enforce
        is_large_core_vm = node.tools[Lscpu].get_core_count() >= 64
        self.use_strict_checks &= is_large_core_vm
        self._set_network_hardware(node=node)
        self._direction = self.NOT_SET
        self._queue_type = self.SINGLE_QUEUE
        self._node = node

    def set_sender(self) -> None:
        self._direction = self.SEND

    def set_receiver(self) -> None:
        self._direction = self.RECV

    def set_multiple_queue(self) -> None:
        self._queue_type = self.MULTI_QUEUE

    def is_mana(self) -> bool:
        return self._hardware == self.MSFT_MANA

    def is_connect_x3(self) -> bool:
        return self._hardware == self.MLX_CX3

    def is_connect_x4(self) -> bool:
        return self._hardware == self.MLX_CX4

    def is_connect_x5(self) -> bool:
        return self._hardware == self.MLX_CX5

    def get_threshold(self) -> int:
        # default nonstrict threshold for pps
        # set up top to appease the type checker
        threshold = 3_000_000
        if self._direction == self.NOT_SET:
            fail(
                "Test bug: testpmd sender/receiver status was "
                "not set before threshold fetch. "
                "Make sure to call vf_helper.set_sender() or"
                "vf_helper.set_receiver() before starting tests."
            )
        if not self.use_strict_checks:
            self._node.log.debug(f"Generated non-strict threshold: {threshold}")
            return threshold

        try:
            dpdk_hw = self._testpmd_thresholds[self._hardware]
            qtype = dpdk_hw[self._queue_type]
            threshold = qtype[self._direction]
        except KeyError:
            fail(
                "Test bug, invalid hardware or direction "
                "key passed to DpdkHardware.get_threshold!"
            )
        self._node.log.debug(f"Generated strict threshold: {threshold}")
        return threshold


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
