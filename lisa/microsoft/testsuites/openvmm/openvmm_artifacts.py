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

FILTERS = {
    CONFIGURATIONS[0]: "all() & !test(pcat) & !test(qemu)",
    CONFIGURATIONS[1]: "all() & !test(pcat)",
    CONFIGURATIONS[2]: "test(linux_x64_snp)",
}


def execution_filter(configuration: str) -> str:
    # Source builds cover Linux guests only. Build-only discovery also includes
    # ignored Windows-host Hyper-V tests, which must not reach execution.
    return f"({FILTERS[configuration]}) & !test(/(?i)windows/) & !test(hyperv)"


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
                "OpenVMM source resolution requires a GitHub repository URL."
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
