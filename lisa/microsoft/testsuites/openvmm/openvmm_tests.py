# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import importlib.util
import shlex
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional, cast

from lisa import (
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.environment import EnvironmentStatus
from lisa.operating_system import CBLMariner, Ubuntu
from lisa.secret import add_secret
from lisa.testsuite import TestResult
from lisa.tools import Ls, Uname
from lisa.tools.usermod import Usermod
from lisa.util import LisaException, SkippedException


@lru_cache(maxsize=1)
def _get_openvmm_tests_type() -> Any:
    module_path = Path(__file__).with_name("openvmm_tests_tool.py")
    spec = importlib.util.spec_from_file_location(
        "lisa_openvmm_tests_tool",
        module_path,
    )
    if not spec or not spec.loader:
        raise RuntimeError(f"failed to load OpenVMM tests helper from {module_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.OpenVmmTests


@TestSuiteMetadata(
    area="openvmm",
    category="community",
    description="""
    This suite runs the upstream OpenVMM vmm_tests from the Linux OpenVMM host.
    """,
)
class OpenVmmUpstreamTestSuite(TestSuite):
    def before_case(self, log: Logger, **kwargs: Any) -> None:
        openvmm_tests_type = _get_openvmm_tests_type()
        node = cast(Node, kwargs["node"])
        host = self._get_initialized_host_node(node)
        if not isinstance(host.os, (CBLMariner, Ubuntu)):
            raise SkippedException(
                f"OpenVMM upstream tests are not implemented for {host.os.name}"
            )

        variables: Dict[str, Any] = cast(Dict[str, Any], kwargs.get("variables", {}))
        repo_url = (
            str(
                variables.get("openvmm_tests_repo", openvmm_tests_type.DEFAULT_REPO)
            ).strip()
            or openvmm_tests_type.DEFAULT_REPO
        )
        auth_token = str(variables.get("openvmm_tests_auth_token", "")).strip()
        if auth_token:
            add_secret(auth_token)

        openvmm_tests = host.tools[openvmm_tests_type]
        openvmm_tests.repo_url = repo_url
        openvmm_tests.auth_token = auth_token

    @TestCaseMetadata(
        description="""
        Run the upstream OpenVMM vmm_tests flowey pipeline on the Linux x64 host.
        Use openvmm_vmm_tests_guest_os=linux|windows|all to scope guest coverage,
        and openvmm_vmm_tests_filter for any additional nextest filter expression.
        Native Linux hosts automatically exclude PCAT coverage because upstream
        PCAT firmware discovery depends on Windows or WSL-hosted firmware paths.
        """,
        priority=2,
        # The full upstream vmm_tests suite can take up to 12 hours on slower
        # hardware; individual filtered runs are much shorter, but a generous
        # ceiling avoids spurious timeouts when running the complete suite.
        timeout=43200,
        requirement=simple_requirement(
            environment_status=EnvironmentStatus.Deployed,
        ),
    )
    def verify_openvmm_upstream_vmm_tests(
        self,
        node: Node,
        log_path: Path,
        result: TestResult,
        variables: Dict[str, Any],
    ) -> None:
        host = self._get_initialized_host_node(node)
        command_group = self._ensure_vmm_tests_supported(host)

        openvmm_tests = host.tools[_get_openvmm_tests_type()]
        openvmm_tests.command_group = command_group or ""
        run_summary = openvmm_tests.run_vmm_tests(
            log_path=log_path,
            ref=str(variables.get("openvmm_tests_ref", "")).strip(),
            release=self._is_truthy(variables.get("openvmm_tests_release", "")),
            test_filter=self._compose_vmm_tests_filter(variables, host),
            install_missing_deps=self._is_truthy(
                variables.get("openvmm_vmm_tests_install_missing_deps", "yes"),
                default=True,
            ),
            skip_vhd_prompt=self._is_truthy(
                variables.get("openvmm_vmm_tests_skip_vhd_prompt", "yes"),
                default=True,
            ),
        )
        result.message = (
            "upstream vmm_tests:\n"
            f"{openvmm_tests.format_run_summary(run_summary, include_failed=False)}"
        )

    def _get_host_node(self, node: Node) -> Any:
        parent: Optional[Node] = cast(Optional[Node], getattr(node, "parent", None))
        if node.__class__.__name__ == "OpenVmmGuestNode":
            if not parent:
                raise SkippedException("OpenVMM guest node does not have a parent host")
            return parent

        return node

    def _get_initialized_host_node(self, node: Node) -> Any:
        host = self._get_host_node(node)
        host.initialize()
        return host

    def _ensure_vmm_tests_supported(self, host: Node) -> Optional[str]:
        hardware_platform = host.tools[Uname].get_linux_information().hardware_platform
        if hardware_platform.lower() != "x86_64":
            raise SkippedException(
                "OpenVMM upstream vmm_tests currently require a Linux x64 host"
            )

        ls = host.tools[Ls]
        has_kvm = ls.path_exists(path="/dev/kvm", sudo=True)
        has_mshv = ls.path_exists(path="/dev/mshv", sudo=True)
        if not has_kvm and not has_mshv:
            raise SkippedException(
                "OpenVMM upstream vmm_tests require /dev/kvm or /dev/mshv on the host"
            )

        if has_kvm:
            host.tools[Usermod].add_user_to_group("kvm", sudo=True)
        if has_mshv:
            host.tools[Usermod].add_user_to_group("mshv", sudo=True)

        command_group: Optional[str] = None
        has_kvm_access = has_kvm and self._can_open_device(host, "/dev/kvm")
        has_mshv_access = has_mshv and self._can_open_device(host, "/dev/mshv")

        if has_mshv and not has_mshv_access:
            has_mshv_access = self._can_open_device(host, "/dev/mshv", group="mshv")
            if has_mshv_access:
                command_group = "mshv"

        if not has_mshv and has_kvm and not has_kvm_access:
            has_kvm_access = self._can_open_device(host, "/dev/kvm", group="kvm")
            if has_kvm_access:
                command_group = "kvm"

        if has_mshv and not has_mshv_access:
            if has_kvm_access:
                raise SkippedException(
                    "OpenVMM upstream vmm_tests detect /dev/mshv before /dev/kvm, "
                    "but the current user cannot open /dev/mshv. Fix /dev/mshv "
                    "permissions or remove /dev/mshv from this host for the run."
                )
            raise SkippedException(
                "OpenVMM upstream vmm_tests require read/write access to /dev/mshv "
                "when it is present on the host, but the current user cannot open it."
            )

        if not has_kvm_access and not has_mshv_access:
            raise SkippedException(
                "OpenVMM upstream vmm_tests require read/write access to /dev/kvm "
                "or /dev/mshv on the host, but the current user cannot open "
                "either device."
            )

        return command_group

    def _can_open_device(
        self,
        host: Node,
        path: str,
        group: str = "",
    ) -> bool:
        open_command = f": <> {path}"
        if group:
            command = f"sg {shlex.quote(group)} -c {shlex.quote(open_command)}"
        else:
            command = open_command
        result = host.execute(
            f"bash -lc {shlex.quote(command)}",
            shell=True,
            expected_exit_code=None,
            no_info_log=True,
            no_error_log=True,
        )
        return result.exit_code == 0

    def _compose_vmm_tests_filter(
        self,
        variables: Dict[str, Any],
        host: Optional[Node] = None,
    ) -> str:
        guest_os = (
            str(
                variables.get(
                    "openvmm_vmm_tests_guest_os",
                    "all",
                )
            )
            .strip()
            .lower()
        )
        custom_filter = str(variables.get("openvmm_vmm_tests_filter", "")).strip()

        guest_filters = {
            "": "",
            "all": "",
            "both": "",
            "linux": "(test(linux_direct) | test(ubuntu) | test(alpine))",
            "windows": "test(windows)",
        }
        if guest_os not in guest_filters:
            raise LisaException(
                "Unsupported value for openvmm_vmm_tests_guest_os. "
                "Use one of: all, both, linux, windows."
            )

        guest_filter = guest_filters[guest_os]

        filters = []
        if guest_filter:
            filters.append(guest_filter)
        if custom_filter:
            filters.append(custom_filter)
        if host and not self._is_wsl_host(host):
            filters.append("!test(pcat)")

        return self._combine_nextest_filters(filters)

    def _combine_nextest_filters(self, filters: Any) -> str:
        normalized = [
            str(filter_value).strip() for filter_value in filters if filter_value
        ]
        if not normalized:
            return ""
        if len(normalized) == 1:
            return normalized[0]
        return " & ".join(f"({filter_value})" for filter_value in normalized)

    def _is_wsl_host(self, host: Node) -> bool:
        kernel_release = host.tools[Uname].get_linux_information().kernel_version_raw
        lowered = kernel_release.lower()
        return "microsoft" in lowered or "wsl" in lowered

    def _is_truthy(self, value: Any, default: bool = False) -> bool:
        if value is None:
            return default
        normalized = str(value).strip().lower()
        if not normalized:
            return default
        return normalized in {"1", "true", "yes", "y", "on"}
