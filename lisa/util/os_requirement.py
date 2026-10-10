# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from dataclasses import dataclass, field
from typing import Optional, Sequence, Type, Union

from semver import VersionInfo

from lisa.operating_system import OperatingSystem, Ubuntu
from lisa.util import LisaException, parse_version


def _parse_release(value: str) -> VersionInfo:
    if not isinstance(value, str) or not re.fullmatch(
        r"[0-9]{2}\.(?:0[1-9]|1[0-2])", value
    ):
        raise LisaException(
            f"Invalid Ubuntu release '{value}': expected YY.MM (for example 22.04)"
        )
    return parse_version(value)


@dataclass(frozen=True)
class OsRequirement:
    """OS restriction with optional Ubuntu release bounds: [min, max)."""

    os_type: Type[OperatingSystem]
    min_version: Optional[str] = None
    max_version: Optional[str] = None
    _minimum: Optional[VersionInfo] = field(init=False, repr=False, default=None)
    _maximum: Optional[VersionInfo] = field(init=False, repr=False, default=None)

    def __post_init__(self) -> None:
        if not isinstance(self.os_type, type) or not issubclass(
            self.os_type, OperatingSystem
        ):
            raise LisaException("OsRequirement requires an OperatingSystem class")
        if self.has_version and self.os_type is not Ubuntu:
            raise LisaException("OS version requirements currently support Ubuntu only")
        minimum = (
            _parse_release(self.min_version) if self.min_version is not None else None
        )
        maximum = (
            _parse_release(self.max_version) if self.max_version is not None else None
        )
        if minimum is not None and maximum is not None and minimum >= maximum:
            raise LisaException(
                "OS min_version must be less than max_version: "
                f"min_version={self.min_version}, max_version={self.max_version}"
            )
        object.__setattr__(self, "_minimum", minimum)
        object.__setattr__(self, "_maximum", maximum)

    @property
    def has_version(self) -> bool:
        return self.min_version is not None or self.max_version is not None

    def matches_release(self, version: VersionInfo) -> bool:
        release = parse_version(f"{version.major}.{version.minor}")
        return (self._minimum is None or release >= self._minimum) and (
            self._maximum is None or release < self._maximum
        )


OsRequirementEntry = Union[Type[OperatingSystem], OsRequirement]


def matches_os_requirement(
    entry: OsRequirementEntry,
    target_os: Type[OperatingSystem],
    version: Optional[VersionInfo] = None,
    *,
    prefilter: bool = False,
) -> Optional[bool]:
    """None means the inferred target is too imprecise to decide."""
    required_os = entry.os_type if isinstance(entry, OsRequirement) else entry
    if not isinstance(required_os, type):
        return False
    direct_match = issubclass(target_os, required_os)
    if not direct_match and not (prefilter and issubclass(required_os, target_os)):
        return False
    if isinstance(entry, OsRequirement) and entry.has_version:
        if not direct_match or version is None:
            return None
        return entry.matches_release(version)
    return True


def is_os_supported(
    entries: Sequence[OsRequirementEntry],
    is_allow_set: bool,
    target_os: Type[OperatingSystem],
    version: Optional[VersionInfo] = None,
    *,
    prefilter: bool = False,
) -> bool:
    matches = [
        matches_os_requirement(entry, target_os, version, prefilter=prefilter)
        for entry in entries
    ]
    if is_allow_set:
        return any(match is not False for match in matches)
    return not any(match is True for match in matches)
