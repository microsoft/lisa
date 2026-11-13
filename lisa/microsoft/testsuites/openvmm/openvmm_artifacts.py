# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import copy
import re
import threading
from typing import Any, Dict, Tuple
from urllib.parse import quote

import requests

from lisa.util import LisaException, constants

# Each canonical upstream configuration has a separate LISA source-test method.
CONFIGURATIONS = (
    "x64-linux-intel-mshv",
    "x64-linux-amd-kvm",
    "x64-linux-amd-snp-mshv",
)

# Native payload targets: KVM uses GNU; Intel/MSHV and SNP/MSHV use MUSL.
GNU = "x86_64-unknown-linux-gnu"
MUSL = "x86_64-unknown-linux-musl"

# These mappings are used only with a validated upstream source contract.
FILTERS = {
    CONFIGURATIONS[0]: "all() & !test(pcat) & !test(qemu)",
    CONFIGURATIONS[1]: "all() & !test(pcat)",
    CONFIGURATIONS[2]: "test(linux_x64_snp)",
}


def execution_filter(configuration: str) -> str:
    # Source builds cover Linux guests only. Build-only discovery also includes
    # ignored Windows-host Hyper-V tests, which must not reach execution.
    return f"({FILTERS[configuration]}) & !test(/(?i)windows/) & !test(hyperv)"


# Ordered upstream files defining the build, artifact layout and execution
# contract. The execution tool fingerprints their normalized checksum records.
CONTRACT_FILES = (
    "flowey/flowey_hvlite/src/pipelines/checkin_gates.rs",
    "flowey/flowey_lib_hvlite/src/init_vmm_tests_content_dir.rs",
    "flowey/flowey_lib_hvlite/src/init_vmm_tests_env.rs",
    "flowey/flowey_lib_hvlite/src/_jobs/consume_and_test_nextest_vmm_tests_archive.rs",
    "flowey/flowey_lib_hvlite/src/test_nextest_vmm_tests_archive.rs",
    "flowey/flowey_lib_hvlite/src/run_cargo_nextest_run.rs",
    "flowey/flowey_lib_common/src/gen_cargo_nextest_run_cmd.rs",
    "flowey/flowey_lib_hvlite/src/install_vmm_tests_external_deps.rs",
    "flowey/flowey_lib_hvlite/src/run_prep_steps.rs",
    "flowey/flowey_lib_hvlite/src/resolve_openvmm_test_linux_kernel.rs",
    "flowey/flowey_lib_hvlite/src/download_release_igvm_files_from_gh.rs",
    "petri/petri_artifacts_core/src/lib.rs",
    "petri/petri_artifacts_common/src/lib.rs",
    "vmm_tests/petri_artifacts_vmm_test/src/lib.rs",
)
# Validated against upstream 61994293a9e5e3bcc1d685d708cf462920eed030.
# Other commits are supported if their contract fingerprint matches; changed
# contracts fail closed until reviewed and added to this allowlist.
SUPPORTED_CONTRACTS = {
    "a3a3e9fcac8124755e43e25f1589e9cb50b4660227f4b6f72597a99e04e0815c",
}

# Guest disk/VMGS filenames and expected byte sizes used by the execution tool
# to download and size-check artifacts, not to provision Azure VMs.
IMAGES = (
    ("nocloud_alpine-3.23.2-x86_64-uefi-cloudinit-r0.vhd", 224494080),
    ("ubuntu-24.04-server-cloudimg-amd64.vhd", 3758211584),
    ("ubuntu-25.04-server-cloudimg-amd64.vhd", 3758211584),
    ("sample-vmgs.vhd", 4194816),
    ("tpm-16k-vmgs.vhd", 4194816),
)
# Additional guests for ARM64 QEMU emulation in the AMD/KVM configuration.
ARM_IMAGES = (
    ("nocloud_alpine-3.23.2-aarch64-uefi-cloudinit-r0.vhd", 258015744),
    ("ubuntu-24.04-server-cloudimg-arm64.vhd", 3758211584),
)

_lock = threading.Lock()
_selections: Dict[Tuple[str, str, str], Dict[str, Any]] = {}


# Resolve source provenance only; building and execution live in the test tool.
# No GitHub Actions build artifacts are selected or downloaded here.
class OpenVmmSource:
    def __init__(self, repository: str, token: str = "") -> None:
        match = re.fullmatch(
            r"https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?/?",
            repository,
        )
        if not match:
            raise LisaException(
                "Upstream configuration validation requires a GitHub repository URL."
            )
        self.repository = match.group(1)
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/vnd.github+json"})
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"

    def _get(self, path: str) -> Any:
        response = self.session.get(
            f"https://api.github.com/repos/{self.repository}/{path}", timeout=60
        )
        if response.status_code in (401, 403):
            raise LisaException(
                "GitHub source resolution failed. Check API rate limits and "
                "repository access; optionally configure openvmm_tests_auth_token."
            )
        response.raise_for_status()
        return response.json()

    def resolve(self, ref: str = "") -> Dict[str, Any]:
        requested_ref = ref.strip() or "main"
        # Pin each repository/ref once per run so profiles share the same commit
        # even if a branch moves. The lock also serializes concurrent resolution.
        key = (str(constants.RUN_LOCAL_LOG_PATH), self.repository, requested_ref)
        with _lock:
            if key not in _selections:
                sha = self._get(f"commits/{quote(requested_ref, safe='')}")["sha"]
                if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
                    raise LisaException(f"Invalid immutable OpenVMM source SHA: {sha}")
                _selections[key] = {
                    "version": 1,
                    "repository": self.repository,
                    "source": "custom-build",
                    "requested_ref": requested_ref,
                    "source_sha": sha,
                    "coverage": "Linux guests only; Windows guest tests excluded",
                }
            # Callers add profile/binary provenance without mutating the cache.
            return copy.deepcopy(_selections[key])
