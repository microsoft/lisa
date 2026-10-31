# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from dataclasses import dataclass, field
from typing import Literal, Optional, Sequence, Type, Union

from semver import VersionInfo

from lisa.operating_system import CBLMariner, OperatingSystem, Redhat, Ubuntu
from lisa.util import LisaException, parse_version

ReleasePrecision = Literal["major", "minor"]


def _parse_release(value: str, os_type: Type[OperatingSystem]) -> VersionInfo:
    pattern = (
        r"[0-9]{2}\.(?:0[1-9]|1[0-2])"
        if os_type is Ubuntu
        else r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
    )
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        expected = "YY.MM (for example 22.04)" if os_type is Ubuntu else "major.minor"
        raise LisaException(
            f"Invalid {os_type.__name__} release '{value}': expected {expected}"
        )
    return parse_version(value)


@dataclass(frozen=True)
class OsRequirement:
    """OS restriction with optional distro release bounds: [min, max)."""

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
        if self.has_version and self.os_type not in (Ubuntu, Redhat, CBLMariner):
            raise LisaException(
                "OS version requirements support Ubuntu, Redhat and CBLMariner only"
            )
        minimum = (
            _parse_release(self.min_version, self.os_type)
            if self.min_version is not None
            else None
        )
        maximum = (
            _parse_release(self.max_version, self.os_type)
            if self.max_version is not None
            else None
        )
        if minimum is not None and maximum is not None and minimum >= maximum:
            raise LisaException(
                "OS min_version must be less than max_version: "
                f"min_version={self.min_version}, max_version={self.max_version}"
            )
        object.__setattr__(self, "_minimum", minimum)
        object.__setattr__(self, "_maximum", maximum)

    def __repr__(self) -> str:
        # Compact form for skip reasons and logs, e.g. Ubuntu[>=20.04,<24.04)
        bounds = []
        if self.min_version is not None:
            bounds.append(f">={self.min_version}")
        if self.max_version is not None:
            bounds.append(f"<{self.max_version}")
        suffix = f"[{','.join(bounds)})" if bounds else ""
        return f"{self.os_type.__name__}{suffix}"

    @property
    def has_version(self) -> bool:
        return self.min_version is not None or self.max_version is not None

    def matches_release(
        self, version: VersionInfo, precision: ReleasePrecision = "minor"
    ) -> Optional[bool]:
        release = parse_version(f"{version.major}.{version.minor}")
        if precision == "major":
            release = parse_version(f"{version.major}.0")
            end = parse_version(f"{version.major + 1}.0")
            if (self._minimum is not None and end <= self._minimum) or (
                self._maximum is not None and release >= self._maximum
            ):
                return False
            if (self._minimum is None or release >= self._minimum) and (
                self._maximum is None or end <= self._maximum
            ):
                return True
            return None
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
    version_precision: ReleasePrecision = "minor",
) -> Optional[bool]:
    """None means the inferred target is too imprecise to decide."""
    required_os = entry.os_type if isinstance(entry, OsRequirement) else entry
    if not isinstance(required_os, type):
        return False
    direct_match = issubclass(target_os, required_os)
    if not direct_match and not (prefilter and issubclass(required_os, target_os)):
        return False
    if isinstance(entry, OsRequirement) and entry.has_version:
        # These release namespaces are concrete products, not their descendants.
        if (
            direct_match
            and required_os in (Redhat, CBLMariner)
            and target_os is not required_os
        ):
            return False
        if not direct_match or version is None:
            return None
        return entry.matches_release(version, version_precision)
    return True


def is_os_supported(
    entries: Sequence[OsRequirementEntry],
    is_allow_set: bool,
    target_os: Type[OperatingSystem],
    version: Optional[VersionInfo] = None,
    *,
    prefilter: bool = False,
    version_precision: ReleasePrecision = "minor",
) -> bool:
    matches = [
        matches_os_requirement(
            entry,
            target_os,
            version,
            prefilter=prefilter,
            version_precision=version_precision,
        )
        for entry in entries
    ]
    if is_allow_set:
        return any(match is not False for match in matches)
    return not any(match is True for match in matches)
