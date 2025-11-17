import re

from lisa import features
from lisa.node import Node
from lisa.tools import Dmesg
from lisa.util import get_matched_str
from lisa.util.logger import filter_ansi_escape

# $ cloud-hypervisor --version
# cloud-hypervisor v41.0.0-41.0.120.g4ea35aaf
VMM_VERSION_PATTERN = re.compile(r"cloud-hypervisor (?P<ch_version>.+)")

# MSHV version:
# [    0.929461] Hyper-V: Host Build 10.0.27924.1000-1-0
MSHV_VERSION_PATTERN = re.compile(
    r"Hyper-V: Host Build \d+\.\d+\.(?P<mshv_version>\d+\.\d+)", re.M
)

# Hyper-V Host version pattern
# [    0.000000] Hyper-V: Host Build 10.0.27924.1000-1-0
HOST_VERSION_PATTERN = re.compile(
    r"Hyper-V:? (?:Host Build|Version)[\s|:][ ]?([^\r\n;]*)", re.M
)

KEY_VMM_VERSION = "vmm_version"
KEY_MSHV_VERSION = "mshv_version"
KEY_HOST_VERSION = "host_version"


def get_vmm_version(node: Node) -> str:
    result: str = "UNKNOWN"
    try:
        if node.is_connected and node.is_posix:
            node.log.debug("detecting vmm version...")
            output = node.execute(
                "cloud-hypervisor --version",
                shell=True,
            ).stdout
            output = filter_ansi_escape(output)
            match = re.search(VMM_VERSION_PATTERN, output.strip())
            if match:
                result = match.group("ch_version")
    except Exception as e:
        node.log.debug(f"error on run vmm: {e}")
    return result


def get_mshv_version(node: Node) -> str:
    result: str = "UNKNOWN"
    try:
        if node.is_connected and node.is_posix:
            node.log.debug("detecting mshv version...")
            try:
                dmesg = node.tools[Dmesg]
                result = get_matched_str(
                    dmesg.get_output(), MSHV_VERSION_PATTERN, first_match=False
                )
            except Exception as e:
                node.log.debug(f"error on run dmesg: {e}")
    except Exception as e:
        node.log.debug(f"error on run mshv: {e}")
    return result


def get_host_version(node: Node) -> str:
    """
    Get Hyper-V Host Build version from dmesg.
    This function is used by Azure, Baremetal, and Hyper-V platforms.
    """
    result: str = ""

    try:
        if node.is_connected and node.is_posix:
            node.log.debug("detecting host version from dmesg...")
            dmesg = node.tools[Dmesg]
            result = get_matched_str(
                dmesg.get_output(), HOST_VERSION_PATTERN, first_match=False
            )
    except Exception as e:
        # It happens on some error VMs. Those errors should be caught earlier in
        # test cases not here. So ignore any error here to collect information only.
        node.log.debug(f"error on run dmesg: {e}")

    # Skip for Windows
    if not node.is_connected or node.is_posix:
        # If not found, try again from serial console log.
        # Skip if node is not initialized.
        if not result and hasattr(node, "features"):
            if node.features.is_supported(features.SerialConsole):
                serial_console = node.features[features.SerialConsole]
                result = serial_console.get_matched_str(HOST_VERSION_PATTERN)

    return result
