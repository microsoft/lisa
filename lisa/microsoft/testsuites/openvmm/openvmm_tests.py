# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import shlex
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, cast

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
from lisa.tools import Ls, Lscpu, Uname
from lisa.tools.lscpu import CpuType
from lisa.tools.usermod import Usermod
from lisa.util import LisaException, SkippedException

from .openvmm_artifacts import CONFIGURATIONS, OpenVmmSource

# Preserve the legacy packaged-binary filter; source validation uses upstream's
# revision-checked configuration at the selected source revision instead.
_MSHV_FILTER = (
    "all() & !test(very_heavy)"
    " & !test(openvmm_openhcl_uefi_x64_windows_datacenter_core_2025_x64_prepped_vbs)"
    " & !test(hyperv_openhcl_pcat)"
    " & !(test(servicing) & test(hyperv))"
    " & !test(pcat_x64)"
    " & !test(qemu)"
)


@lru_cache(maxsize=1)
def _get_openvmm_tests_type() -> Any:
    from .openvmm_tests_tool import OpenVmmTests

    return OpenVmmTests


# Orchestrate host selection and source provenance here; the tool builds and
# executes upstream Rust tests and records the selected binary's VMM version.
@TestSuiteMetadata(
    area="openvmm",
    category="community",
    description="""
    This suite builds and runs upstream OpenVMM vmm_tests on Linux hosts.
    Select verify_openvmm_upstream_vmm_tests_intel_mshv,
    verify_openvmm_upstream_vmm_tests_amd_kvm, or
    verify_openvmm_upstream_vmm_tests_amd_snp_mshv for the matching host.
    Source tests always build the resolved commit; a blank openvmm_tests_ref
    pins main once per LISA run. They do not download GitHub Actions archives.
    Windows guest tests are excluded, and incompatible hosts are skipped.
    vmm_version reports the selected OpenVMM executable's version, also recorded
    in the source manifest or packaged-binary provenance.
    The legacy openvmm_vmm_tests_profile variable applies only to the separate
    packaged-binary test; remove it from source-test runbooks.
    """,
    requirement=simple_requirement(
        # MSHV is not suite-wide: the Ubuntu configuration uses KVM instead.
        supported_os=[CBLMariner, Ubuntu],
    ),
    maturity="preview",
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
        # Prefer an explicit test repository, then the installer repository,
        # before falling back to upstream OpenVMM.
        repo_url = (
            str(variables.get("openvmm_tests_repo", "")).strip()
            or str(variables.get("openvmm_installer_repo", "")).strip()
            or openvmm_tests_type.DEFAULT_REPO
        )
        auth_token = str(variables.get("openvmm_tests_auth_token", "")).strip()
        if auth_token:
            add_secret(auth_token)

        openvmm_tests = self._get_openvmm_tests(
            host, openvmm_tests_type, repo_url, auth_token
        )
        openvmm_tests.configure_repository(repo_url, auth_token)

    def _get_openvmm_tests(
        self,
        host: Node,
        openvmm_tests_type: Any,
        repo_url: str,
        auth_token: str,
    ) -> Any:
        create_tool = getattr(host.tools, "create", None)
        if callable(create_tool):
            return create_tool(
                openvmm_tests_type, repo_url=repo_url, auth_token=auth_token
            )

        return host.tools[openvmm_tests_type]

    # Separate source-test entry points fix the profile independently of runbook
    # variables; all three share the orchestration in _run_configuration.
    @TestCaseMetadata(
        description="""
        Build and run Linux guest tests for x64-linux-intel-mshv on an Intel
        Azure Linux host with /dev/mshv. Resolve openvmm_tests_ref (default main)
        to an immutable commit before building. Windows guests are excluded.
        Unsupported source contracts fail before building.
        """,
        priority=2,
        timeout=43200,
        requirement=simple_requirement(
            environment_status=EnvironmentStatus.Deployed,
            supported_os=[CBLMariner],
        ),
    )
    def verify_openvmm_upstream_vmm_tests_intel_mshv(
        self,
        node: Node,
        log_path: Path,
        result: TestResult,
        variables: Dict[str, Any],
    ) -> None:
        self._run_configuration(node, log_path, result, variables, CONFIGURATIONS[0])

    @TestCaseMetadata(
        description="""
        Build and run Linux guest tests for x64-linux-amd-kvm on an AMD Ubuntu
        host with /dev/kvm and without /dev/mshv, including ARM64 QEMU emulation.
        Resolve openvmm_tests_ref (default main) to an immutable commit before
        building. Windows guests are excluded; unsupported source contracts fail.
        """,
        priority=2,
        timeout=43200,
        requirement=simple_requirement(
            environment_status=EnvironmentStatus.Deployed,
            supported_os=[Ubuntu],
        ),
    )
    def verify_openvmm_upstream_vmm_tests_amd_kvm(
        self,
        node: Node,
        log_path: Path,
        result: TestResult,
        variables: Dict[str, Any],
    ) -> None:
        self._run_configuration(node, log_path, result, variables, CONFIGURATIONS[1])

    @TestCaseMetadata(
        description="""
        Build and run Linux SNP guest tests for x64-linux-amd-snp-mshv on an AMD
        Azure Linux host with /dev/mshv and SNP guest-launch support. Resolve
        openvmm_tests_ref (default main) to an immutable commit before building.
        Windows guests are excluded; unsupported source contracts fail.
        """,
        priority=2,
        timeout=43200,
        requirement=simple_requirement(
            environment_status=EnvironmentStatus.Deployed,
            supported_os=[CBLMariner],
        ),
    )
    def verify_openvmm_upstream_vmm_tests_amd_snp_mshv(
        self,
        node: Node,
        log_path: Path,
        result: TestResult,
        variables: Dict[str, Any],
    ) -> None:
        self._run_configuration(node, log_path, result, variables, CONFIGURATIONS[2])

    def _run_configuration(
        self,
        node: Node,
        log_path: Path,
        result: TestResult,
        variables: Dict[str, Any],
        profile: str,
    ) -> None:
        host = self._get_initialized_host_node(node)
        # Source validation must retain the selected upstream profile's complete
        # Linux-only coverage; legacy profile/custom-filter knobs are package-only.
        if str(variables.get("openvmm_vmm_tests_profile", "")).strip():
            raise LisaException(
                "Source-test profiles are fixed by the selected test method. "
                "Remove openvmm_vmm_tests_profile and select the matching test."
            )
        if (
            str(variables.get("openvmm_vmm_tests_guest_os", "all")).strip().lower()
            not in ("", "all", "both")
            or str(variables.get("openvmm_vmm_tests_filter", "")).strip()
        ):
            raise LisaException(
                "Upstream configurations require their complete upstream filter. "
                "Remove openvmm_vmm_tests_guest_os/filter overrides."
            )
        self._ensure_configuration_host(host, profile)
        openvmm_tests = host.tools[_get_openvmm_tests_type()]
        openvmm_tests.command_group = self._ensure_vmm_tests_supported(host) or ""
        ref = str(variables.get("openvmm_tests_ref", "")).strip()
        source = OpenVmmSource(openvmm_tests.repo_url, openvmm_tests.auth_token)
        # Blank refs resolve main; pin an immutable SHA before building so the
        # execution and reported provenance identify the same source revision.
        manifest = source.resolve(ref)
        install_deps = self._is_truthy(
            variables.get("openvmm_vmm_tests_install_missing_deps", "yes"),
            default=True,
        )
        # Delegate contract checks, native build/preparation and nextest execution.
        run_summary = openvmm_tests.run_vmm_tests(
            log_path=log_path,
            configuration=profile,
            manifest=manifest,
            install_missing_deps=install_deps,
        )
        result.message = (
            f"upstream vmm_tests: {profile}, {manifest['source_sha']}, "
            f"{manifest['source']}\n"
            f"Coverage: {manifest['coverage']}\n"
            f"{openvmm_tests.format_run_summary(run_summary, include_failed=False)}"
        )

    def _ensure_configuration_host(self, host: Node, configuration: str) -> None:
        # Case metadata restricts the OS; runtime checks also enforce CPU vendor
        # and hypervisor devices on the actual host, skipping incompatible hosts.
        kvm = configuration == "x64-linux-amd-kvm"
        expected_os = Ubuntu if kvm else CBLMariner
        expected_cpu = (
            CpuType.Intel if configuration == "x64-linux-intel-mshv" else CpuType.AMD
        )
        if not isinstance(host.os, expected_os):
            raise SkippedException(
                f"{configuration} requires {expected_os.__name__}, not {host.os.name}"
            )
        if host.tools[Lscpu].get_cpu_type() != expected_cpu:
            raise SkippedException(f"{configuration} requires a {expected_cpu} host")
        device = "/dev/kvm" if kvm else "/dev/mshv"
        if not host.tools[Ls].path_exists(device, sudo=True):
            raise SkippedException(f"{configuration} requires {device}")
        if kvm and host.tools[Ls].path_exists("/dev/mshv", sudo=True):
            raise SkippedException(
                "The KVM configuration requires a host without /dev/mshv; "
                "upstream would otherwise select MSHV instead of KVM."
            )
        # SNP guest launches validate hypervisor support, not Linux SEV CPUID flags.

    @TestCaseMetadata(
        description=(
            "Run upstream OpenVMM community tests against the OS package binary. "
            "Install the OpenVMM RPM if missing, or skip if unavailable in the OS "
            "repositories. Use existing Flowey build-only "
            "preparation for the harness, firmware and guest agents, then replace "
            "the staged OpenVMM with the packaged executable before running tests. "
            "Requires an explicit binary path. Select the harness from the RPM "
            "version's upstream tag, falling back to main if absent, or override "
            "with openvmm_tests_ref. Verify real test "
            "execution and that the installed binary remains unchanged.\n"
            "This test is generated by the lisa_test_writer prompt."
        ),
        priority=2,
        timeout=43200,
        requirement=simple_requirement(
            environment_status=EnvironmentStatus.Connected,
            supported_os=[CBLMariner],
            supported_host_capabilities=["mshv"],
        ),
        tags=["ai-generated"],
    )
    def verify_openvmm_pkg_using_upstream_vmm_tests(
        self,
        node: Node,
        log_path: Path,
        result: TestResult,
        variables: Dict[str, Any],
    ) -> None:
        # Keep installed-package validation separate from source-profile builds;
        # its existing guest/filter overrides remain available.
        host = self._get_initialized_host_node(node)
        command_group = self._ensure_vmm_tests_supported(host)
        openvmm_tests = host.tools[_get_openvmm_tests_type()]
        openvmm_tests.command_group = command_group or ""
        test_filter = self._combine_nextest_filters(
            ["test(openvmm_)", self._compose_vmm_tests_filter(variables, host)]
        )
        run_summary = openvmm_tests.run_vmm_tests_prebuilt_binary(
            log_path=log_path,
            binary_path=str(variables.get("openvmm_prebuilt_binary_path", "")).strip(),
            ref=str(variables.get("openvmm_tests_ref", "")).strip(),
            release=self._is_truthy(variables.get("openvmm_tests_release", "")),
            test_filter=test_filter,
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
            "upstream vmm_tests (prebuilt binary):\n"
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

        virtualization_enabled = host.tools[Lscpu].is_virtualization_enabled()
        ls = host.tools[Ls]
        has_kvm = ls.path_exists(path="/dev/kvm", sudo=True)
        has_mshv = ls.path_exists(path="/dev/mshv", sudo=True)
        if not virtualization_enabled and not has_kvm and not has_mshv:
            raise SkippedException("Virtualization is not enabled in hardware")

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
        profile = str(variables.get("openvmm_vmm_tests_profile", "")).strip().lower()
        if profile not in {"", "custom", "linux-intel-mshv"}:
            raise LisaException(
                "Unsupported packaged-binary profile. Use custom or linux-intel-mshv."
            )
        if profile == "linux-intel-mshv":
            if guest_os not in {"", "all", "both"} or custom_filter:
                raise LisaException(
                    "The linux-intel-mshv profile requires all guests and no custom "
                    "filter. Use the custom profile for a restricted test selection."
                )
            return _MSHV_FILTER

        # Current Linux-direct test names use linux_; retain distro-name matches
        # for UEFI guests in this packaged-binary filter.
        guest_filters = {
            "": "",
            "all": "",
            "both": "",
            "linux": "(test(linux_) | test(ubuntu) | test(alpine))",
            "windows": "test(windows)",
        }
        if guest_os not in guest_filters:
            raise LisaException(
                "Unsupported value for openvmm_vmm_tests_guest_os. "
                "Use one of: all, both, linux, windows."
            )

        guest_filter = guest_filters[guest_os]

        filters: List[str] = []
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
