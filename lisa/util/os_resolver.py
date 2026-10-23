# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""
Helpers to resolve a target operating system class from a free-form name or
from runbook variables. Used by the test selector to pre-filter test cases
that are not applicable to the target distro, avoiding the overhead of
deploying environments only to skip the cases at runtime.
"""

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Type

from semver import VersionInfo

from lisa.operating_system import (
    CBLMariner,
    CentOs,
    Debian,
    OperatingSystem,
    Oracle,
    Redhat,
    Ubuntu,
)
from lisa.util import parse_version
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
    "azlinux": "CBLMariner",
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
    "shared_gallery",
    "community_gallery_image",
    "vhd",
    "image",
)

# Aliases shorter than this length must appear at a token boundary in the
# original image string to avoid false positives from plain substring matches
# (e.g. 'ol' inside 'golden-image.vhd').
_SHORT_ALIAS_LEN_THRESHOLD = 4

_UBUNTU_RELEASES = {
    "xenial": "16.04",
    "bionic": "18.04",
    "focal": "20.04",
    "jammy": "22.04",
    "noble": "24.04",
    "questing": "25.10",
    "resolute": "26.04",
}


@dataclass(frozen=True)
class TargetOs:
    os_type: Type[OperatingSystem]
    version: Optional[VersionInfo] = None
    version_upper_bound: Optional[VersionInfo] = None


def _image_definition_name(image: str) -> str:
    text = re.split(r"[?#]", image.lower().strip(), maxsplit=1)[0]
    segments = text.rstrip("/").split("/")
    if "images" in segments:
        index = segments.index("images") + 1
        return segments[index] if index < len(segments) else ""
    if len(segments) > 1:
        return (
            segments[-2]
            if re.fullmatch(r"(?:[0-9]+\.)*[0-9]+|latest", segments[-1])
            else segments[-1]
        )
    return text


def _infer_ubuntu_release(image: str) -> Optional[VersionInfo]:
    if "," in image:
        _log.debug("Ubuntu version pre-filter deferred: multiple image identifiers")
        return None
    text = image.lower().strip()
    parts = text.split()
    marketplace = len(parts) == 4 and parts[0] == "canonical"
    if marketplace:
        # Publication versions are not distro releases.
        text = " ".join(parts[1:3])
    else:
        text = _image_definition_name(text)

    if "ubuntu" not in text:
        _log.debug(
            "Ubuntu version pre-filter deferred: image name does not identify Ubuntu"
        )
        return None

    releases = set()
    for codename, release in _UBUNTU_RELEASES.items():
        if re.search(rf"(?:^|[^a-z0-9]){codename}(?:$|[^a-z0-9])", text):
            releases.add(parse_version(release))

    patterns = [
        (
            r"(?:^|[^a-z0-9])ubuntu[-_](\d{2})[._](\d{2})(?![a-z0-9]|[._]\d)",
            text,
        )
    ]
    if marketplace:
        patterns.append(
            (
                r"^(?:pro-fips-)?(\d{2})[._](\d{2})(?![a-z0-9]|[._]\d)",
                parts[2],
            )
        )
    for pattern, source in patterns:
        for match in re.finditer(pattern, source):
            if not 1 <= int(match[2]) <= 12:
                _log.debug(
                    f"Ubuntu version pre-filter deferred: invalid release in '{image}'"
                )
                return None
            releases.add(parse_version(f"{match[1]}.{match[2]}"))
    if len(releases) == 1:
        return releases.pop()
    _log.debug(
        "Ubuntu version pre-filter deferred: "
        f"unknown or conflicting release in '{image}'"
    )
    return None


def _marketplace_release_sources(
    parts: List[str], os_type: Type[OperatingSystem]
) -> List[str]:
    publisher, offer, sku, _ = parts
    if publisher == "microsoftcblmariner" and os_type is CBLMariner:
        if offer in ("azure-linux-3", "cbl-mariner"):
            return [offer, sku]
    elif publisher == "debian" and os_type is Debian:
        if re.fullmatch(r"debian-[0-9]+", offer):
            return [offer, f"debian-{sku}"]
    elif (
        (
            publisher == "redhat"
            and os_type is Redhat
            and offer in ("rhel", "rhel-arm64", "rhel-cvm")
        )
        or (publisher == "oracle" and os_type is Oracle and offer == "oracle-linux")
        or (
            publisher == "openlogic"
            and os_type is CentOs
            and offer in ("centos", "centos-lvm")
        )
    ):
        if os_type is Oracle:
            sku = re.sub(r"^ol", "", sku)
        # These catalog forms encode major 6-10 followed by the minor.
        compact = re.fullmatch(r"(10|[6-9])([0-9]{1,2})(?=[-_]|$)(.*)", sku)
        if compact:
            sku = f"{compact[1]}.{int(compact[2])}{compact[3]}"
        if re.match(r"^[0-9]{1,2}(?:[._][0-9]+)?(?=$|[-_])", sku):
            return [f"{os_type.__name__.lower()}-{sku}"]
    _log.debug("Version pre-filter deferred: unrecognized publisher/offer/SKU")
    return []


def _infer_distro_release(
    image: str, os_type: Type[OperatingSystem]
) -> Tuple[Optional[VersionInfo], Optional[VersionInfo]]:
    """Return a release and, for incomplete releases, its exclusive upper bound."""
    prefixes: Dict[Type[OperatingSystem], str] = {
        CBLMariner: r"(?:azure[-_]?linux|cbl[-_]?mariner|mariner)",
        Redhat: r"(?:rhel|redhat)",
        Debian: r"debian",
        Oracle: r"(?:oracle[-_]?linux|oracle|ol)",
        CentOs: r"centos",
    }
    if os_type not in prefixes:
        return None, None
    if "," in image:
        _log.debug("Version pre-filter deferred: multiple image identifiers")
        return None, None
    parts = image.lower().split()
    sources = (
        _marketplace_release_sources(parts, os_type)
        if len(parts) == 4
        else [_image_definition_name(image)]
    )

    pattern = (
        rf"(?:^|[^a-z0-9]){prefixes[os_type]}[-_]"
        r"([0-9]+)(?:[._]([0-9]+))?(?![a-z0-9]|[._][0-9])"
    )
    intervals = []
    for source in sources:
        for match in re.finditer(pattern, source):
            major = int(match[1])
            minor = int(match[2]) if match[2] is not None else None
            lower = parse_version(f"{major}.{minor or 0}")
            upper = (
                parse_version(str(major + 1))
                if minor is None
                else parse_version(f"{major}.{minor + 1}")
            )
            intervals.append((lower, upper, minor is not None))
    if intervals:
        lower = max(item[0] for item in intervals)
        upper = min(item[1] for item in intervals)
        if lower < upper:
            return lower, None if any(item[2] for item in intervals) else upper
    _log.debug(
        f"{os_type.__name__} version pre-filter deferred: "
        f"unknown or conflicting release in '{image}'"
    )
    return None, None


def resolve_target_os(variables: Dict[str, Any]) -> Optional[TargetOs]:
    """Apply the shared opt-in gate for runner and CLI listing."""
    gate = variables.get("enable_distro_pre_filtering")
    if str(getattr(gate, "data", gate)).lower() not in ("true", "1", "yes"):
        return None
    return infer_target_os_info(variables)


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
    # Normalize text (remove non-alphanumeric) so aliases with separators
    # (e.g. 'cbl-mariner' vs 'cblmariner') match reliably.
    normalized_text = re.sub(r"[^a-z0-9]+", "", text)
    # Sort aliases by length (longest first) so 'cblmariner' wins over
    # 'mariner' if both happen to be present, and 'almalinux' wins over 'alma'.
    for alias in sorted(_OS_ALIASES.keys(), key=len, reverse=True):
        if len(alias) < _SHORT_ALIAS_LEN_THRESHOLD:
            # Short aliases (e.g. 'ol', 'azl', 'bsd') are too prone to false
            # hits via plain substring match (e.g. 'golden-image.vhd' contains
            # 'ol'). Require them to appear at a token boundary in the
            # original text: preceded by start-of-string or a non-alphanumeric
            # separator, and followed by a digit, separator, or end-of-string
            # so common prefixes like 'ol9-lvm-gen2' still match.
            pattern = rf"(?:^|[^a-z0-9]){re.escape(alias)}(?:[0-9]|[^a-z0-9]|$)"
            if not re.search(pattern, text):
                continue
        elif alias not in normalized_text:
            continue
        cls = resolve_os_class(alias)
        if cls is not None:
            return cls
    return None


def infer_target_os(
    variables: Optional[Dict[str, Any]],
) -> Optional[Type[OperatingSystem]]:
    target = infer_target_os_info(variables)
    return target.os_type if target else None


def infer_target_os_info(
    variables: Optional[Dict[str, Any]],
) -> Optional[TargetOs]:
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
                if cls is Ubuntu:
                    version, upper_bound = _infer_ubuntu_release(value), None
                else:
                    version, upper_bound = _infer_distro_release(value, cls)
                if version is not None:
                    _log.info(
                        f"target {cls.__name__} release inferred as '{version}'"
                        f", upper_bound={upper_bound}"
                    )
                return TargetOs(cls, version, upper_bound)

    # Nothing to go on.
    return None
