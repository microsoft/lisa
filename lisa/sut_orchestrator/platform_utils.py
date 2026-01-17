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
            
            # Check if SSH session is actually active before attempting operations
            try:
                # First, try to extract version from git repository (most reliable for Docker-based tests)
                node.log.debug("Trying to detect VMM version from git repository...")
                git_repo_paths = [
                    "~/lisa_working/tool/cloudhypervisortests/cloud-hypervisor",
                    "$HOME/lisa_working/tool/cloudhypervisortests/cloud-hypervisor",
                ]
                
                for repo_path in git_repo_paths:
                    git_cmd = f"bash -c 'cd {repo_path} 2>/dev/null && git describe --tags --always --dirty 2>&1'"
                    node.log.debug(f"Trying git repository at: {repo_path}")
                    git_result = node.execute(git_cmd, shell=True, sudo=False)
                    
                    if git_result.exit_code == 0 and git_result.stdout.strip():
                        version_str = git_result.stdout.strip()
                        node.log.debug(f"Git describe output: '{version_str}'")
                        
                        # Extract version from git describe output (e.g., "msft/v48.0.235" or "v48.0.235-7-g6fed5f8e7")
                        # Try to match version patterns: msft/v48.0.235 or v48.0.235 or v48.0.235-7-gabcd123
                        version_match = re.search(r'(?:msft/)?v?([\d.]+(?:-[\da-f]+)?(?:-g[0-9a-f]+)?)', version_str)
                        if version_match:
                            result = version_match.group(1)
                            node.log.debug(f"Successfully detected VMM version from git repository: {result}")
                            return result
                        else:
                            # If no version pattern, return the full git describe output
                            node.log.debug(f"Using git describe output as version: {version_str}")
                            return version_str
                
                # Git repository not found, try local binary
                node.log.debug("Git repository not found, attempting to detect VMM version from local binary: cloud-hypervisor --version")
                local_check = node.execute(
                    "cloud-hypervisor --version",
                    shell=True,
                )
            except Exception as ssh_error:
                # If SSH fails (e.g., session not active), skip version detection gracefully
                if "SSH session not active" in str(ssh_error) or "SSHException" in type(ssh_error).__name__:
                    node.log.debug(f"SSH session not available for VMM version detection, returning UNKNOWN")
                    return result
                else:
                    # Re-raise if it's a different error
                    raise
            
            node.log.debug(f"Local binary check: exit_code={local_check.exit_code}, stdout='{local_check.stdout.strip()}', stderr='{local_check.stderr.strip()}'")
            
            if local_check.exit_code == 0:
                node.log.debug("Local binary found, parsing version...")
                output = filter_ansi_escape(local_check.stdout)
                match = re.search(VMM_VERSION_PATTERN, output.strip())
                if match:
                    result = match.group("ch_version")
                    node.log.debug(f"Successfully detected VMM version from local binary: {result}")
                    return result
                else:
                    node.log.debug(f"Local binary responded but version pattern not matched. Output: '{output.strip()}'")
            
            # If local binary not found, try Docker container
            node.log.debug("Local cloud-hypervisor binary not found (exit_code != 0), attempting Docker fallback...")
            
            # First, check what cloud-hypervisor Docker images are already on the system
            node.log.debug("Checking for existing cloud-hypervisor Docker images...")
            docker_images_check = node.execute(
                "docker images --format '{{.Repository}}:{{.Tag}}' | grep -i cloud-hypervisor | head -5",
                shell=True,
                sudo=True,
            )
            node.log.debug(f"Existing Docker images check: exit_code={docker_images_check.exit_code}, output='{docker_images_check.stdout.strip()}'")
            
            # Parse available images from the output
            available_images = []
            if docker_images_check.exit_code == 0 and docker_images_check.stdout.strip():
                available_images = [img.strip() for img in docker_images_check.stdout.strip().split('\n') if img.strip()]
                node.log.debug(f"Found {len(available_images)} cloud-hypervisor Docker image(s): {available_images}")
            
            # If no images found, try common fallback images
            if not available_images:
                node.log.debug("No cloud-hypervisor images found locally, trying common image names...")
                available_images = [
                    "ghcr.io/cloud-hypervisor/cloud-hypervisor:latest",
                    "mcr.microsoft.com/cloud-hypervisor:latest",
                ]
            
            # Try each available image
            for docker_image in available_images:
                node.log.debug(f"Trying Docker image: {docker_image}")
                
                # First, inspect the image to understand its entrypoint
                inspect_cmd = f"docker inspect {docker_image} --format='{{{{json .Config}}}}' 2>&1"
                node.log.debug(f"Inspecting Docker image with command: {inspect_cmd}")
                inspect_result = node.execute(inspect_cmd, shell=True, sudo=True)
                node.log.debug(f"Docker inspect result: exit_code={inspect_result.exit_code}, output='{inspect_result.stdout[:500]}'")
                
                # Try to find the cloud-hypervisor binary inside the container
                find_cmd = f"docker run --rm {docker_image} bash -c 'find / -name cloud-hypervisor -type f -executable 2>/dev/null | head -1' 2>&1"
                node.log.debug(f"Searching for binary inside container: {find_cmd}")
                find_result = node.execute(find_cmd, shell=True, sudo=True)
                node.log.debug(f"Binary search result: exit_code={find_result.exit_code}, stdout='{find_result.stdout.strip()}'")
                
                if find_result.exit_code == 0 and find_result.stdout.strip():
                    binary_path = find_result.stdout.strip().split('\n')[0]
                    node.log.debug(f"Found binary at: {binary_path}")
                    version_cmd = f"docker run --rm --entrypoint {binary_path} {docker_image} --version 2>&1"
                    node.log.debug(f"Trying to get version with found binary: {version_cmd}")
                    version_result = node.execute(version_cmd, shell=True, sudo=True)
                    node.log.debug(f"Version check result: exit_code={version_result.exit_code}, stdout='{version_result.stdout.strip()}'")
                    
                    if version_result.exit_code == 0:
                        output = filter_ansi_escape(version_result.stdout)
                        match = re.search(VMM_VERSION_PATTERN, output.strip())
                        if match:
                            result = match.group("ch_version")
                            node.log.debug(f"Successfully detected VMM version from Docker ({docker_image}): {result}")
                            return result
                
                # If binary not found via search, try running with explicit entrypoint
                docker_cmd = f"docker run --rm --entrypoint /usr/local/bin/cloud-hypervisor {docker_image} --version 2>&1"
                node.log.debug(f"Docker command (with explicit entrypoint): {docker_cmd}")
                
                docker_check = node.execute(
                    docker_cmd,
                    shell=True,
                    sudo=True,
                )
                
                node.log.debug(f"Docker check for {docker_image}: exit_code={docker_check.exit_code}, stdout='{docker_check.stdout.strip()}', stderr='{docker_check.stderr.strip()}'")
                
                if docker_check.exit_code == 0:
                    node.log.debug(f"Docker container {docker_image} responded successfully, parsing version...")
                    output = filter_ansi_escape(docker_check.stdout)
                    match = re.search(VMM_VERSION_PATTERN, output.strip())
                    if match:
                        result = match.group("ch_version")
                        node.log.debug(f"Successfully detected VMM version from Docker ({docker_image}): {result}")
                        return result
                    else:
                        node.log.debug(f"Docker responded but version pattern not matched. Output: '{output.strip()}'")
                else:
                    # Try alternate binary paths if explicit entrypoint failed
                    node.log.debug(f"First attempt failed, trying alternate binary paths...")
                    alternate_paths = [
                        "cloud-hypervisor",  # Use default entrypoint
                        "/usr/bin/cloud-hypervisor",
                        "/cloud-hypervisor",
                    ]
                    
                    for binary_path in alternate_paths:
                        alt_cmd = f"docker run --rm --entrypoint {binary_path} {docker_image} --version 2>&1"
                        node.log.debug(f"Trying alternate path: {alt_cmd}")
                        alt_result = node.execute(alt_cmd, shell=True, sudo=True)
                        node.log.debug(f"Alternate path result: exit_code={alt_result.exit_code}, stdout='{alt_result.stdout.strip()[:200]}', stderr='{alt_result.stderr.strip()[:200]}'")
                        
                        if alt_result.exit_code == 0:
                            output = filter_ansi_escape(alt_result.stdout)
                            match = re.search(VMM_VERSION_PATTERN, output.strip())
                            if match:
                                result = match.group("ch_version")
                                node.log.debug(f"Successfully detected VMM version from Docker with alternate path ({docker_image}, {binary_path}): {result}")
                                return result
                    
                    node.log.debug(f"Docker image {docker_image} failed with all attempted paths")
            
            node.log.debug(f"Could not detect VMM version from local binary or Docker. Final result: {result}")
                
    except Exception as e:
        node.log.debug(f"Exception during VMM version detection: {type(e).__name__}: {e}")
        import traceback
        node.log.debug(f"Traceback: {traceback.format_exc()}")
    
    node.log.debug(f"Returning VMM version: {result}")
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
