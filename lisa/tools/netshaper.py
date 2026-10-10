# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
from dataclasses import dataclass
from decimal import Decimal
from shlex import quote
from typing import Any, Dict, List, Optional, Type

from lisa.executable import ExecutableResult, Tool
from lisa.operating_system import CBLMariner, Linux
from lisa.tools.gcc import Gcc
from lisa.tools.git import Git
from lisa.tools.make import Make
from lisa.util import LisaException, SkippedException, UnsupportedOperationException


@dataclass
class NetShaperInfo:
    scope: str
    id: Optional[int] = None
    bw_min: Optional[Decimal] = None
    bw_max: Optional[Decimal] = None
    parent_scope: Optional[str] = None
    parent_id: Optional[int] = None
    weight: Optional[int] = None
    raw: str = ""


class NetShaper(Tool):
    """Configure hardware rate limiting with upstream iproute2 netshaper."""

    _repo = "https://github.com/iproute2/iproute2.git"
    _show_pattern = re.compile(
        r"dev:\s+(?P<dev>\S+)\s+scope\s+(?P<scope>netdev|queue|node)"
        r"(?:\s+id\s+(?P<id>\d+))?(?P<attrs>(?:\s+\S+)*)"
    )
    _rate_pattern = re.compile(
        r"(?P<value>\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)(?P<unit>[kKMGTPE]?bit)"
    )

    @property
    def command(self) -> str:
        return str(self.get_tool_path() / "iproute2" / "netshaper" / "netshaper")

    @property
    def can_install(self) -> bool:
        return isinstance(self.node.os, Linux)

    @property
    def dependencies(self) -> List[Type[Tool]]:
        return [Git, Make, Gcc]

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        self._built = False

    def _check_exists(self) -> bool:
        return self._built and super()._check_exists()

    def _install(self) -> bool:
        if not isinstance(self.node.os, Linux):
            raise UnsupportedOperationException(
                "Building iproute2 requires Linux; use a Linux test node."
            )
        if isinstance(self.node.os, CBLMariner):
            self.node.os.install_packages(["glibc-devel", "binutils", "kernel-headers"])
        self.node.os.install_packages(["bison", "flex"])
        for alternatives in (("pkg-config", "pkgconf"), ("libmnl-dev", "libmnl-devel")):
            package = next(
                (
                    name
                    for name in alternatives
                    if self.node.os.is_package_in_repo(name)
                ),
                None,
            )
            if package is None:
                raise LisaException(
                    f"Cannot build iproute2: none of {alternatives} is available. "
                    "Enable a repository providing the development dependencies."
                )
            self.node.os.install_packages(package)
        git = self.node.tools[Git]
        source = git.clone(
            self._repo, self.get_tool_path(), dir_name="iproute2", fail_on_exists=False
        )
        git.run("fetch origin main", cwd=source, force_run=True, expected_exit_code=0)
        git.checkout("FETCH_HEAD", cwd=source)
        revision = git.run(
            "rev-parse HEAD", cwd=source, force_run=True, expected_exit_code=0
        ).stdout.strip()
        self._log.info(f"Building upstream iproute2 main revision {revision}")
        self.node.execute(
            "./configure",
            cwd=source,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "iproute2 configure failed; check build dependencies."
            ),
        )
        make = self.node.tools[Make]
        arguments = "PREFIX=/usr/local SBINDIR=/usr/local/sbin"
        make.make(arguments, cwd=source, is_clean=True)
        self.node.execute(
            f"{quote(self.command)} -V",
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "netshaper was not built; check libmnl configure output."
            ),
        )
        make.make(f"install {arguments}", cwd=source, sudo=True)
        self._built = True
        self._log.info(
            self.run("-V", force_run=True, expected_exit_code=0).stdout.strip()
        )
        return self._check_exists()

    def _invoke(self, parameters: str) -> ExecutableResult:
        return self.run(parameters, sudo=True, force_run=True)

    def get_error(self, result: ExecutableResult) -> str:
        return "\n".join(
            text.strip() for text in (result.stderr, result.stdout) if text.strip()
        )

    def get_shapers(
        self, interface: str, scope: str, shaper_id: int
    ) -> List[NetShaperInfo]:
        """Read one requested handle, not all shapers on the interface."""
        result = self._invoke(
            f"show dev {quote(interface)} handle scope {quote(scope)} id {shaper_id}"
        )
        if result.exit_code != 0:
            error = self.get_error(result)
            family_missing = (
                "RTNETLINK answers: No such file or directory" in error
                and "Error talking to the kernel" in error
            )
            if family_missing or re.search(
                r"(?i)(?:failed to resolve|cannot resolve|not found).*net_shaper"
                r"|net_shaper.*not found",
                error,
            ):
                raise SkippedException(
                    f"Kernel net_shaper family is unavailable on {interface}: "
                    f"{error}. Use a kernel with CONFIG_NET_SHAPER enabled."
                )
            if re.search(
                r"(?i)net_shaper.*not supported"
                r"|(?:RTNETLINK answers: )?Operation not supported",
                error,
            ):
                raise SkippedException(
                    f"Cannot read shapers on {interface}: {error}. "
                    "Use a kernel and driver supporting net_shaper operations."
                )
            if (
                "RTNETLINK answers: No such file or directory" in error
                and "Kernel command failed:" in error
            ):
                return []
            raise LisaException(
                f"Cannot read shapers on {interface}: {error}. "
                "Check the interface, permissions and kernel net_shaper diagnostics."
            )
        output = result.stdout.strip()
        matched = self._show_pattern.fullmatch(output)
        if (
            matched is None
            or matched["dev"] != interface
            or matched["scope"] != scope
            or (matched["id"] is None and scope != "netdev")
            or (matched["id"] is not None and int(matched["id"]) != shaper_id)
        ):
            raise LisaException(
                f"Cannot parse netshaper show output: {output!r}. "
                "Check the upstream CLI output format."
            )
        attributes = matched["attrs"].split()
        values: Dict[str, Any] = {}
        if len(attributes) % 2:
            raise LisaException(
                f"Incomplete netshaper attributes: {output!r}. "
                "Check the upstream CLI output format."
            )
        for name, value in zip(attributes[::2], attributes[1::2]):
            if name in values:
                raise LisaException(
                    f"Duplicate netshaper attribute: {output!r}. "
                    "Check the upstream CLI output format."
                )
            if name in ("bw-min", "bw-max"):
                values[name] = self._parse_rate(value)
            elif name in ("parent-id", "weight") and value.isdigit():
                values[name] = int(value)
            elif name == "parent-scope" and value in ("netdev", "queue", "node"):
                values[name] = value
            else:
                raise LisaException(
                    f"Unexpected netshaper attribute: {output!r}. "
                    "Check the upstream CLI output format."
                )
        return [
            NetShaperInfo(
                scope=matched["scope"],
                id=int(matched["id"]) if matched["id"] else None,
                bw_min=values.get("bw-min"),
                bw_max=values.get("bw-max"),
                parent_scope=values.get("parent-scope"),
                parent_id=values.get("parent-id"),
                weight=values.get("weight"),
                raw=output,
            )
        ]

    def _parse_rate(self, value: str) -> Decimal:
        matched = self._rate_pattern.fullmatch(value)
        if matched is None:
            raise LisaException(
                f"Unrecognized netshaper rate {value!r}; check CLI bit units."
            )
        unit = matched["unit"][:-3].upper()
        exponent = "KMGTPE".index(unit) + 1 if unit else 0
        return Decimal(matched["value"]).scaleb(3 * exponent)

    def set_shaper(
        self,
        interface: str,
        bw_max: int,
        scope: str,
        shaper_id: int,
        metric: str,
    ) -> ExecutableResult:
        if metric != "bps":
            raise UnsupportedOperationException(
                f"Upstream netshaper cannot set metric {metric!r}: the CLI only "
                "supports implicit bps through bit units and has no metric switch. "
                "Use bps or investigate an upstream CLI upgrade for this metric."
            )
        result = self._invoke(
            f"set dev {quote(interface)} handle scope {quote(scope)} "
            f"id {shaper_id} bw-max {bw_max}bit"
        )
        if result.exit_code != 0:
            error = self.get_error(result)
            if re.search(
                r"(?i)net_shaper.*not supported"
                r"|(?:RTNETLINK answers: )?Operation not supported",
                error,
            ):
                raise SkippedException(
                    f"Cannot set shaper on {interface}: {error}. "
                    "Use a kernel and driver supporting net_shaper operations."
                )
        return result

    def delete_shaper(
        self, interface: str, scope: str, shaper_id: int
    ) -> ExecutableResult:
        return self._invoke(
            f"delete dev {quote(interface)} handle scope {quote(scope)} id {shaper_id}"
        )
