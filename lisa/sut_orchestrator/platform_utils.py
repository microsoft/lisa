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
    """
    Detects cloud-hypervisor VMM version from cached value, local binary,
    or git repository.

    Checks in order:
    1. Cached value from CloudHypervisorTests tool (if installed)
    2. Local binary (fast, works for most installations)
    3. Git repository (for Docker-based tests where binaries are compiled on-demand)

    Returns version string (e.g., "48.0.235") or "UNKNOWN" if detection fails.
    """
    result: str = "UNKNOWN"
    try:
        # Check if CloudHypervisorTests tool has already cached the version.
        # This lookup does not require SSH connectivity and should be usable
        # even during teardown when the node may be disconnected.
        extended_resources = getattr(node.capability, "extended_resources", None)
        if extended_resources:
            cached_version: str = extended_resources.get(
                KEY_VMM_VERSION,
                "UNKNOWN",
            )
            if cached_version and cached_version != "UNKNOWN":
                node.log.debug(f"Using cached VMM version: {cached_version}")
                return cached_version

        # If there is no cached value, only proceed with SSH-based detection
        # when the node is connected and running a POSIX-compatible OS.
        if not (node.is_connected and node.is_posix):
            return result

        node.log.debug("detecting vmm version...")
        # Primary method: Try local binary installation (fast, works for most cases)
        node.log.debug("Trying local binary: cloud-hypervisor --version")
        local_result = node.execute(
            "cloud-hypervisor --version", shell=True, sudo=False
        )

        if local_result.exit_code == 0:
            output = filter_ansi_escape(local_result.stdout)
            match = re.search(VMM_VERSION_PATTERN, output.strip())
            if match:
                result = match.group("ch_version")
                node.log.debug(
                    f"Successfully detected VMM version from local binary: {result}"
                )
                return result

        # Fallback method: Extract version from git repository
        # For Docker-based tests where cloud-hypervisor is compiled from source
        node.log.debug("Local binary not found, trying git repository...")

        # Use standard LISA tool path where CloudHypervisorTests clones repo
        git_repo_path = "~/lisa_working/tool/cloudhypervisortests/cloud-hypervisor"
        git_cmd = (
            f"bash -c 'cd {git_repo_path} 2>/dev/null && "
            "git describe --tags --always --dirty 2>&1'"
        )
        git_result = node.execute(git_cmd, shell=True, sudo=False)

        if git_result.exit_code == 0 and git_result.stdout.strip():
            version_str = git_result.stdout.strip()
            node.log.debug(f"Git describe output: '{version_str}'")

            # Strip -dirty suffix if present
            version_str = version_str.replace("-dirty", "")

            # Extract clean version number from git describe output
            # Handles patterns: "msft/v48.0.235", "v48.0.235-7-g6fed5f8e7", "v48.0.235"
            # Extracts only the tag version, excluding commit count and hash suffixes
            version_match = re.search(r"(?:msft/)?v?([\d.]+)", version_str)
            if version_match:
                result = version_match.group(1)
                node.log.debug(
                    f"Successfully detected VMM version from git repository: {result}"
                )
                return result

    except Exception as e:
        node.log.debug(f"Error during VMM version detection: {type(e).__name__}: {e}")

    node.log.debug(f"VMM version detection result: {result}")
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
