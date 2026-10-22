# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from pathlib import PurePath
from typing import Any, Dict

import toml

from lisa.util import LisaException

CARGO_CONFIG_PROBE = r"""
import json
import os
import sys
from pathlib import Path

output = Path(sys.argv[1])
for key, allowed in (
    ("CARGO_PROFILE_RELEASE_DEBUG", ("2", "true", "full")),
    ("CARGO_PROFILE_RELEASE_STRIP", ("none", "false")),
):
    value = os.environ.get(key)
    if value is not None and value not in allowed:
        raise RuntimeError(f"{key} conflicts with CH diagnostic build settings")

cwd = Path.cwd()
cargo_home = Path(os.environ.get("CARGO_HOME") or Path.home() / ".cargo").absolute()
directories = [directory / ".cargo" for directory in (cwd, *cwd.parents)]
directories.append(cargo_home)
config_path = None
for directory in directories:
    for name in ("config", "config.toml"):
        candidate = directory / name
        if candidate.exists():
            config_path = candidate
            break
    if config_path is not None:
        break

if config_path is None:
    config_path = cargo_home / "config.toml"
    content = ""
else:
    content = config_path.read_text(encoding="utf-8")

(output / "cargo-original.toml").write_text(content, encoding="utf-8")
(output / "cargo-config-path.json").write_text(
    json.dumps(str(config_path)), encoding="utf-8"
)
for name in ("cargo-original.toml", "cargo-config-path.json"):
    (output / name).chmod(0o644)
"""


def _parse_config(content: str, name: str) -> Dict[str, Any]:
    try:
        config: Dict[str, Any] = toml.loads(content)
        return config
    except toml.TomlDecodeError:
        # Cargo configuration can contain registry credentials.
        raise LisaException(f"Invalid {name} TOML for CH diagnostics") from None


def _table(parent: Dict[str, Any], key: str) -> Dict[str, Any]:
    value = parent.setdefault(key, {})
    if not isinstance(value, dict):
        raise LisaException(f"CH diagnostics require a TOML table for '{key}'")
    return value


def create_cargo_config(content: str) -> str:
    config = _parse_config(content, "Cargo")
    release = _table(_table(config, "profile"), "release")
    release.update(debug=2, strip="none")
    environment = _table(config, "env")
    environment["RUST_BACKTRACE"] = {"value": "full", "force": True}
    environment["RUST_LIB_BACKTRACE"] = {"value": "1", "force": True}
    serialized: str = toml.dumps(config)
    return serialized


def create_nextest_config(content: str) -> str:
    config = _parse_config(content, "Nextest")
    profiles = _table(config, "profile")
    if not profiles:
        raise LisaException("CH diagnostics require existing Nextest profiles")

    has_report_path = False
    for profile in profiles.values():
        if not isinstance(profile, dict):
            raise LisaException("CH diagnostics require Nextest profile tables")
        junit = _table(profile, "junit")
        report_path = junit.get("path")
        if report_path is not None:
            if not isinstance(report_path, str) or not report_path:
                raise LisaException(
                    "CH diagnostics require nonempty JUnit report paths"
                )
            has_report_path = True
        junit.update({"store-success-output": True, "store-failure-output": True})

        overrides = profile.get("overrides", [])
        if not isinstance(overrides, list):
            raise LisaException("CH diagnostics require a Nextest overrides array")
        for override in overrides:
            if not isinstance(override, dict):
                raise LisaException("CH diagnostics require Nextest override tables")
            _table(override, "junit").update(
                {"store-success-output": True, "store-failure-output": True}
            )

    if not has_report_path:
        raise LisaException(
            "CH diagnostics require existing Nextest JUnit report paths"
        )
    serialized: str = toml.dumps(config)
    return serialized


def diagnostic_volume(
    source: PurePath, target: PurePath, read_only: bool = True
) -> str:
    # dev_cli splits on '#' and expands volume arguments without shell quoting.
    for path in (source, target):
        if not re.fullmatch(r"/[A-Za-z0-9_./-]+", str(path)):
            raise LisaException(
                f"CH diagnostic volume path is unsupported by dev_cli: {path}"
            )
    mode = "ro" if read_only else "rw"
    return f"{source}:{target}:{mode}"
