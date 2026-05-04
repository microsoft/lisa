# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""
Helpers to resolve a target operating system class from a free-form name or
from runbook variables. Used by the test selector to pre-filter test cases
that are not applicable to the target distro, avoiding the overhead of
deploying environments only to skip the cases at runtime.
"""

import re
from typing import Any, Dict, Optional, Type

from lisa.operating_system import OperatingSystem
from lisa.util.logger import get_logger

_log = get_logger("init", "os_resolver")

# Known short names / aliases that map to a concrete OperatingSystem subclass.
# Keys are normalized (lowercased, no separators); values are class names that
# must exist in lisa.operating_system. The map intentionally favors common
# distro brand names and acronyms over exact class names so users do not need
# to know LISA's internal naming.
_OS_ALIASES: Dict[str, str] = {
    # Debian family
    "ubuntu": "Ubuntu",
    "canonical": "Ubuntu",
    "debian": "Debian",
    # Red Hat family
    "rhel": "Redhat",
    "redhat": "Redhat",
    "centos": "CentOs",
    "openlogic": "CentOs",
    "oracle": "Oracle",
    "ol": "Oracle",
    "almalinux": "AlmaLinux",
    "alma": "AlmaLinux",
    # SUSE family
    "suse": "Suse",
    "sles": "SLES",
    "opensuse": "Suse",
    # Fedora
    "fedora": "Fedora",
    # Azure Linux / CBL-Mariner (same product, multiple brand names)
    "azurelinux": "CBLMariner",
    "azl": "CBLMariner",
    "mariner": "CBLMariner",
    "cblmariner": "CBLMariner",
    "microsoftcblmariner": "CBLMariner",
    # BSD family
    "freebsd": "FreeBSD",
    "microsoftcbsd": "FreeBSD",
    "openbsd": "OpenBSD",
    "bsd": "BSD",
    # Other
    "alpine": "Alpine",
    "coreos": "CoreOs",
    "flatcar": "CoreOs",
    "kinvolk": "CoreOs",
    "linux": "Linux",
    "windows": "Windows",
}

# Variable keys that may carry an image string from which the distro can be
# inferred.
_IMAGE_VAR_KEYS = (
    "marketplace_image",
    "shared_gallery_image",
    "community_gallery_image",
    "vhd",
    "image",
)


def _normalize(name: str) -> str:
    """Lowercase and strip non-alphanumerics so 'CBL-Mariner', 'cbl_mariner'
    and 'cblmariner' all resolve identically."""
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def _all_os_subclasses() -> Dict[str, Type[OperatingSystem]]:
    """Walk the OperatingSystem class tree and return {normalized_name: cls}."""
    found: Dict[str, Type[OperatingSystem]] = {}
    stack = [OperatingSystem]
    while stack:
        cls = stack.pop()
        found[_normalize(cls.__name__)] = cls
        stack.extend(cls.__subclasses__())
    return found


def resolve_os_class(name: Optional[str]) -> Optional[Type[OperatingSystem]]:
    """Map a string like 'ubuntu' or 'azurelinux' to an OperatingSystem
    subclass. Returns None when the name is empty, unknown, or refers to a
    class that no longer exists.
    """
    if not name:
        return None

    normalized = _normalize(name)
    if not normalized:
        return None

    # First consult the alias map, then fall back to a direct class-name match.
    target_class_name = _OS_ALIASES.get(normalized)
    candidates = _all_os_subclasses()
    if target_class_name:
        cls = candidates.get(_normalize(target_class_name))
        if cls is not None:
            return cls

    return candidates.get(normalized)


def _infer_from_image_string(image: str) -> Optional[Type[OperatingSystem]]:
    """Best-effort inference of an OS class from an image identifier
    (marketplace 'publisher offer sku version' string, gallery name, vhd path,
    etc.). Matches the longest alias substring found in the lowercased image
    text to avoid false hits on short tokens.
    """
    if not image:
        return None
    # Strip common Azure URL domain suffixes that contain OS-like substrings
    # (e.g. '.windows.net', 'blob.core.windows.net') before matching.
    text = re.sub(
        r"(\.blob\.core\.windows\.net|\.windows\.net|\.azure\.com)", "", image.lower()
    )
    # Sort aliases by length (longest first) so 'cblmariner' wins over
    # 'mariner' if both happen to be present, and 'almalinux' wins over 'alma'.
    matches = []
    for alias in sorted(_OS_ALIASES.keys(), key=len, reverse=True):
        if alias in text:
            matches.append(alias)
    for alias in matches:
        cls = resolve_os_class(alias)
        if cls is not None:
            return cls
    return None


def infer_target_os(
    variables: Optional[Dict[str, Any]],
) -> Optional[Type[OperatingSystem]]:
    """Infer the target OS from image-related runbook variables.

    Checks common image variable keys (marketplace, gallery, vhd) and
    extracts the distro from the image string.  Returns None when no
    image variable is set or the distro cannot be determined — the
    caller should treat None as 'no pre-filter'.
    """
    if not variables:
        return None

    def _unwrap(raw: Any) -> Any:
        # Runners pass ``Dict[str, VariableEntry]`` while the list/CLI path
        # passes ``Dict[str, Any]`` of already-unwrapped values. Accept both
        # by duck-typing on the ``data`` attribute that ``VariableEntry``
        # exposes, without importing the variable module here.
        return getattr(raw, "data", raw)

    # Infer from any provided image identifier.
    for key in _IMAGE_VAR_KEYS:
        value = _unwrap(variables.get(key))
        if isinstance(value, str) and value.strip():
            cls = _infer_from_image_string(value)
            if cls is not None:
                _log.info(
                    f"target_os inferred as '{cls.__name__}' "
                    f"(source: variable '{key}'='{value}')"
                )
                return cls

    # Nothing to go on.
    return None
