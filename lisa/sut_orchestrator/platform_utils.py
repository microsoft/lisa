import re

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

KEY_VMM_VERSION = "vmm_version"
KEY_MSHV_VERSION = "mshv_version"


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
