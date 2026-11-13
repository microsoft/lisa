# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import hashlib
import json
import re
import shlex
import sys
import xml.etree.ElementTree as ETree
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path, PurePath
from typing import Any, Dict, Iterator, List, Optional, Tuple, Type, cast

from lisa.executable import Tool
from lisa.operating_system import CBLMariner, Posix, Ubuntu
from lisa.sut_orchestrator.platform_utils import _cache_vmm_version_in_node
from lisa.tools import Cargo, Curl, Git, Ls, Uname
from lisa.tools.openvmm import VERSION_PATTERN
from lisa.util import LisaException, SkippedException, UnsupportedDistroException

from .openvmm_artifacts import (
    ARM_IMAGES,
    CONFIGURATIONS,
    CONTRACT_FILES,
    GNU,
    IMAGES,
    MUSL,
    SUPPORTED_CONTRACTS,
    execution_filter,
)


def _new_str_list() -> List[str]:
    return []


@dataclass
class _JUnitSummary:
    tests: int = 0
    total: int = 0
    passed: int = 0
    failures: int = 0
    errors: int = 0
    skipped: int = 0
    has_nextest_summary: bool = False
    failed_tests: List[str] = field(default_factory=_new_str_list)
    passed_tests: List[str] = field(default_factory=_new_str_list)


class OpenVmmTests(Tool):
    # Restoring packages (cargo xflowey restore-packages) can take up to 1 hour
    # on first run due to large dependency downloads; subsequent runs are faster.
    RESTORE_TIMEOUT = 3600
    # The full vmm_tests suite can take up to 12 hours on slower hardware.
    # Individual filtered runs are faster, but allow the full ceiling to avoid
    # spurious timeouts when running the complete suite.
    VMM_TIMEOUT = 43200
    NEXTEST_LINUX_X64_TARGET = "x86_64-unknown-linux-gnu"
    # Flowey puts Unix sockets below --dir/temp; Linux socket paths must fit 108 bytes.
    _ANSI_ESCAPE_PATTERN = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
    _SUMMARY_PATTERN = re.compile(
        r"Summary \[[^\]\r\n]+\]\s+(?P<run>\d+)(?:/(?P<total>\d+))? tests? run:"
        r"[ \t]*(?P<counts>[^\r\n]+)"
    )
    _FAILED_TEST_PATTERN = re.compile(
        r"^[ \t]*(?:FAIL|TIMEOUT|EXECFAIL|ABORT)[ \t]+\[[^\]\r\n]+\][ \t]+"
        r"(?:\([ \t]*\d+/\d+\)[ \t]+)?"
        r"(?P<name>\S+(?:[ \t]+|[ \t]*\r?\n[ \t]+)\S[^\r\n]*)$",
        re.MULTILINE,
    )
    _PASSED_TEST_PATTERN = re.compile(
        r"^[ \t]*PASS[ \t]+\[[^\]\r\n]+\][ \t]+"
        r"(?:\([ \t]*\d+/\d+\)[ \t]+)?"
        r"(?P<name>\S+(?:[ \t]+|[ \t]*\r?\n[ \t]+)\S[^\r\n]*)$",
        re.MULTILINE,
    )

    DEFAULT_REPO = "https://github.com/microsoft/openvmm.git"
    repo_url = DEFAULT_REPO
    auth_token = ""
    command_group = ""

    _distro_package_mapping = {
        CBLMariner.__name__: [
            "gcc",
            "openssl-devel",
            "perl",
            "pkg-config",
            "binutils",
            "glibc-devel",
        ],
        Ubuntu.__name__: ["build-essential", "libssl-dev", "perl", "pkg-config"],
    }

    repo_root: PurePath
    _artifact_root: PurePath
    _prepared_ref: Optional[str]
    _repo_prepared: bool

    @property
    def command(self) -> str:
        return self.node.tools[Cargo].command

    @property
    def can_install(self) -> bool:
        return True

    @property
    def dependencies(self) -> List[Type[Tool]]:
        return [Git, Curl, Ls]

    @classmethod
    def create(cls, node: Any, *args: Any, **kwargs: Any) -> "OpenVmmTests":
        repo_url = str(kwargs.pop("repo_url", "")).strip()
        auth_token = str(kwargs.pop("auth_token", "")).strip()
        if args:
            repo_url = str(args[0]).strip()
        if len(args) > 1:
            auth_token = str(args[1]).strip()
        if len(args) > 2 or kwargs:
            raise LisaException(
                "OpenVmmTests.create accepts only repo_url and auth_token. "
                "Remove any extra tool creation arguments."
            )

        tool = cls(node)
        tool.repo_url = repo_url or cls.DEFAULT_REPO
        tool.auth_token = auth_token
        return tool

    def _check_exists(self) -> bool:
        self._set_repo_paths()
        return self.node.tools[Ls].path_exists(str(self.repo_root))

    def configure_repository(self, repo_url: str, auth_token: str) -> None:
        repository_changed = self.repo_url != repo_url or self.auth_token != auth_token

        self.repo_url = repo_url
        self.auth_token = auth_token
        self._set_repo_paths()
        if not repository_changed:
            return

        self._prepared_ref = None
        self._repo_prepared = False
        self._exists = None

    def run_vmm_tests(
        self,
        log_path: Path,
        configuration: str,
        manifest: Dict[str, Any],
        install_missing_deps: bool = True,
    ) -> _JUnitSummary:
        # Source builds never fall back to CI artifacts.
        if manifest["source"] != "custom-build":
            raise LisaException(
                "OpenVMM upstream tests require a source-build manifest."
            )
        _cache_vmm_version_in_node(self.node, "UNKNOWN")
        selected_filter = execution_filter(configuration)
        manifest = dict(
            manifest, configuration=configuration, execution_filter=selected_filter
        )
        log_path.mkdir(parents=True, exist_ok=True)
        (log_path / "openvmm_manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )
        self._log.info(f"OpenVMM source provenance: {json.dumps(manifest)}")
        with self._native_workspace(
            manifest["source_sha"], log_path, install_missing_deps
        ) as env:
            name = "openvmm_vmm_tests"
            local_junit = log_path / f"{name}.junit.xml"
            local_junit.unlink(missing_ok=True)
            with self._short_temp_path(self.repo_root / "input") as input_dir:
                try:
                    self._validate_native_contract()
                    self._build_native_content(
                        configuration,
                        input_dir,
                        selected_filter,
                        env,
                        log_path,
                        install_missing_deps,
                    )
                    target = GNU if configuration == CONFIGURATIONS[1] else MUSL
                    binary_path = str(input_dir / target / "openvmm")
                    manifest["binary_version"] = self._record_vmm_version(binary_path)
                    manifest["binary_path"] = binary_path
                    (log_path / "openvmm_manifest.json").write_text(
                        json.dumps(manifest, indent=2), encoding="utf-8"
                    )
                    env.update(
                        VMM_TESTS_CONTENT_DIR=str(input_dir),
                        VMM_TEST_IMAGES=str(input_dir / "images"),
                        TEST_OUTPUT_PATH=str(input_dir / "test_results"),
                        TMPDIR=str(input_dir / "temp"),
                        PETRI_REMOTE_ARTIFACTS="0",
                        RUST_BACKTRACE="1",
                        RUST_LOG="trace",
                    )
                    if configuration == CONFIGURATIONS[1]:
                        env["OPENVMM_REQUIRE_2MB_HUGETLB"] = "1"
                    with self._prepare_native_execution(
                        configuration,
                        input_dir,
                        env,
                        log_path,
                        install_missing_deps,
                    ):
                        command = shlex.join(
                            [
                                self.node.tools[Cargo].command,
                                "nextest",
                                "run",
                                "--profile",
                                "ci",
                                "--config-file",
                                str(self.repo_root / ".config/nextest.toml"),
                                "--workspace-remap",
                                str(self.repo_root),
                                "--archive-file",
                                str(input_dir / target / "vmm_tests.tar.zst"),
                                "--filter-expr",
                                selected_filter,
                            ]
                        )
                        self._run_logged_command(
                            name=name,
                            command=self._wrap_command_for_group(
                                f"ulimit -c unlimited && "
                                f"{self._native_environment_prefix(configuration)} "
                                f"{command}"
                            ),
                            log_path=log_path,
                            timeout=self.VMM_TIMEOUT,
                            update_envs=env,
                        )
                finally:
                    # Preserve diagnostics from build, setup and execution before
                    # the temporary source worktree is removed.
                    self._collect_native_results(log_path, local_junit)
                if not local_junit.exists():
                    raise LisaException(
                        "Native OpenVMM execution produced no JUnit report"
                    )
                return self._check_vmm_tests_results(
                    name, log_path / f"{name}.log", local_junit
                )

    def _build_native_content(
        self,
        configuration: str,
        output: PurePath,
        test_filter: str,
        env: Dict[str, str],
        log_path: Path,
        install_missing_deps: bool,
    ) -> None:
        emulated = configuration == CONFIGURATIONS[1]
        # KVM retains ARM64 QEMU coverage; the MSHV profiles use x64 MUSL.
        targets = [MUSL] + (["aarch64-unknown-linux-musl"] if emulated else [])
        if install_missing_deps:
            if emulated:
                cast(Posix, self.node.os).install_packages(
                    ["gcc-aarch64-linux-gnu", "qemu-user-static", "binfmt-support"]
                )
            self._run_logged_command(
                "openvmm_prepare_build_targets",
                "rustup target add " + shlex.join(targets),
                log_path,
                self.RESTORE_TIMEOUT,
                env,
            )
            self._restore_packages(log_path, env, include_emulated=emulated)
        self._ensure_cargo_nextest(log_path, env, install_missing_deps)
        # Let upstream Flowey build the Linux-only payload, then execute its
        # nextest archive separately so LISA can validate results and provenance.
        command = [
            self.node.tools[Cargo].command,
            "xflowey",
            "vmm-tests-run",
            "--target",
            "linux-x64" if emulated else "linux-musl-x64",
            "--filter",
            test_filter,
            "--dir",
            str(output),
            "--release",
            "--build-only",
            "--ci-profile",
            "--skip-vhd-prompt",
            "--no-reuse-prepped-vhds",
            "--no-lazy-fetch",
        ]
        if emulated:
            command.append("--include-emulated")
        if install_missing_deps:
            command.append("--install-missing-deps")
        self._run_logged_command(
            "openvmm_build_artifacts",
            shlex.join(command),
            log_path,
            self.VMM_TIMEOUT,
            env,
        )
        windows_helper = output / "x86_64-pc-windows-msvc" / "pipette.exe"
        self.node.execute(
            f"test ! -e {shlex.quote(str(windows_helper))}",
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "Linux-only custom build unexpectedly produced a Windows guest helper"
            ),
        )

    @contextmanager
    def _native_workspace(
        self, sha: str, log_path: Path, install_missing_deps: bool = True
    ) -> Iterator[Dict[str, str]]:
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise LisaException(f"Invalid immutable OpenVMM source SHA: {sha}")
        if not self._check_exists() and not self._install():
            raise LisaException("failed to install the OpenVMM source repository")
        # Isolate the pinned source without changing the base checkout.
        original_repo, original_artifacts = self.repo_root, self._artifact_root
        arguments = []
        if self.auth_token:
            arguments.extend(
                ["-c", f"http.extraheader=AUTHORIZATION: bearer {self.auth_token}"]
            )
        arguments.extend(["fetch", "origin", sha])
        self.node.tools[Git].run(
            shlex.join(arguments),
            cwd=original_repo,
            shell=True,
            force_run=True,
            update_envs={"GIT_TERMINAL_PROMPT": "0"},
            expected_exit_code=0,
        )
        working_path = str(self.node.working_path).rstrip("/")
        workspace = self.node.execute(
            f"mktemp -d {shlex.quote(working_path)}/ovn-XXXXXXXX",
            shell=True,
            expected_exit_code=0,
        ).stdout.strip()
        if not re.fullmatch(
            rf"{re.escape(working_path)}/ovn-[A-Za-z0-9]{{8}}", workspace
        ):
            raise LisaException(f"Unexpected OpenVMM workspace: {workspace!r}")
        added = False
        try:
            self.node.tools[Git].run(
                shlex.join(["worktree", "add", "--detach", workspace, sha]),
                cwd=original_repo,
                shell=True,
                force_run=True,
                expected_exit_code=0,
            )
            added = True
            self.repo_root = self.node.get_pure_path(workspace)
            self._artifact_root = self.repo_root / "logs"
            self.node.execute(
                f"mkdir -p {shlex.quote(str(self._artifact_root))} && "
                "git submodule update --init --recursive",
                cwd=self.repo_root,
                shell=True,
                timeout=self.RESTORE_TIMEOUT,
                expected_exit_code=0,
                update_envs={"GIT_TERMINAL_PROMPT": "0"},
            )
            env = self._get_cargo_environment()
            # Build with the selected checkout's Rust pin, not the host default.
            pin = self.node.execute(
                "cat flowey/flowey_lib_hvlite/src/cfg_rustup_version.rs",
                cwd=self.repo_root,
                shell=True,
                expected_exit_code=0,
            ).stdout
            match = re.search(
                r'pub const RUSTUP_TOOLCHAIN:\s*&str\s*=\s*"'
                r'(?P<version>\d+\.\d+\.\d+|nightly-\d{4}-\d{2}-\d{2})";',
                pin,
            )
            if not match:
                raise LisaException("Unrecognized upstream Rust toolchain pin")
            version = match.group("version")
            env["RUSTUP_TOOLCHAIN"] = version
            env["GH_PROMPT_DISABLED"] = "1"
            env["GIT_TERMINAL_PROMPT"] = "0"
            if self.auth_token:
                env["GH_TOKEN"] = self.auth_token
            prepare_rust = (
                f"rustup toolchain install {version} --profile minimal --no-self-update"
                if install_missing_deps
                else f"rustup run {version} rustc --version"
            )
            self._run_logged_command(
                "openvmm_prepare_rust",
                prepare_rust,
                log_path,
                self.RESTORE_TIMEOUT,
                env,
            )
            yield env
        finally:
            # Restore tool paths and report cleanup failures without masking an
            # earlier build/test exception.
            has_error = sys.exc_info()[0] is not None
            self.repo_root, self._artifact_root = original_repo, original_artifacts
            cleanup = (
                f"git worktree remove --force {shlex.quote(workspace)}"
                if added
                else f"rmdir -- {shlex.quote(workspace)}"
            )
            result = self.node.execute(
                cleanup, cwd=original_repo, shell=True, expected_exit_code=None
            )
            if result.exit_code:
                self._log.error(f"OpenVMM workspace cleanup failed: {result.stderr}")
                if not has_error:
                    raise LisaException("failed to remove OpenVMM workspace")

    @contextmanager
    def _short_temp_path(self, target: PurePath) -> Iterator[PurePath]:
        alias = self._create_short_temp_path(target)
        try:
            yield alias
        finally:
            self.node.execute(
                f"rm -f -- {shlex.quote(str(alias))}",
                shell=True,
                expected_exit_code=None,
                no_info_log=True,
            )

    def _create_short_temp_path(self, target: PurePath) -> PurePath:
        alias = self.node.execute(
            "mktemp -d /tmp/ovi-XXXXXXXX",
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "failed to create a short path for OpenVMM temporary files"
            ),
        ).stdout.strip()
        if not re.fullmatch(r"/tmp/ovi-[A-Za-z0-9]{8}", alias):
            raise LisaException(f"Unexpected OpenVMM temporary path: {alias!r}")
        try:
            self.node.execute(
                f"mkdir -p -- {shlex.quote(str(target))} && "
                f"rmdir -- {shlex.quote(alias)} && "
                f"ln -s -- {shlex.quote(str(target))} {shlex.quote(alias)}",
                shell=True,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    "failed to link the OpenVMM working-volume content directory"
                ),
            )
        except Exception:
            self.node.execute(
                f"rm -f -- {shlex.quote(alias)}",
                shell=True,
                expected_exit_code=None,
                no_info_log=True,
            )
            raise
        return self.node.get_pure_path(alias)

    def _validate_native_contract(self) -> None:
        result = self.node.execute(
            "sha256sum " + shlex.join(CONTRACT_FILES),
            cwd=self.repo_root,
            shell=True,
            expected_exit_code=0,
        )
        # SSH may return CRLF records; normalize them before comparing the
        # maintained contract fingerprint, without weakening source validation.
        checksums = "\n".join(result.stdout.strip().splitlines())
        digest = hashlib.sha256(checksums.encode("utf-8")).hexdigest()
        if digest not in SUPPORTED_CONTRACTS:
            raise LisaException(
                f"Unsupported upstream configuration/content contract: {digest}. "
                "Update and validate the Python profile mappings before executing "
                "this revision; no Rust source will be injected or patched."
            )
        self._log.info(f"Validated upstream contract: {digest}")

    @staticmethod
    def _native_environment_prefix(configuration: str) -> str:
        # Do not inherit settings that reuse guest disks or hide unstable failures.
        prefix = "env -u PETRI_REUSE_PREPPED_VHDS -u PETRI_IGNORE_UNSTABLE_FAILURES"
        if configuration != CONFIGURATIONS[1]:
            prefix += " -u OPENVMM_REQUIRE_2MB_HUGETLB"
        return prefix

    @contextmanager
    def _prepare_native_execution(
        self,
        configuration: str,
        content: PurePath,
        env: Dict[str, str],
        log_path: Path,
        install_missing_deps: bool,
    ) -> Iterator[None]:
        self._ensure_cargo_nextest(log_path, env, install_missing_deps)
        paths = [content / "temp", content / "test_results", content / "images"]
        self.node.execute(
            "mkdir -p " + shlex.join([str(path) for path in paths]) + " && "
            f"find {shlex.quote(str(content))} -type f "
            "\\( -name openvmm -o -name openvmm_vhost -o -name pipette "
            "-o -name prep_steps -o -name tmk_vmm -o -name qemu-system-aarch64 "
            "\\) -exec chmod a+x {} +",
            shell=True,
            expected_exit_code=0,
        )
        device = "/dev/kvm" if configuration == CONFIGURATIONS[1] else "/dev/mshv"
        vsock = "/dev/vhost-vsock"
        hugepage_path = (
            "/sys/kernel/mm/hugepages/hugepages-2048kB/" "nr_overcommit_hugepages"
        )
        original_hugepage_value: Optional[str] = None
        original_vsock_acl: Optional[str] = None
        acl_user: Optional[str] = None
        changed_hugepage_value = False
        try:
            if install_missing_deps:
                # vhost_vsock is a host-global module and is not unloaded here;
                # force LISA to discard this host even if later setup fails.
                self.node.mark_dirty()
                setup = []
                if configuration != CONFIGURATIONS[2]:
                    setup.extend(["modprobe vhost_vsock", "udevadm settle"])
                if configuration == CONFIGURATIONS[1]:
                    original_hugepage_value = self.node.execute(
                        f"cat {shlex.quote(hugepage_path)}",
                        shell=True,
                        expected_exit_code=0,
                        expected_exit_code_failure_message=(
                            "failed to read the original hugepage overcommit limit"
                        ),
                    ).stdout.strip()
                    if not original_hugepage_value.isdigit():
                        raise LisaException(
                            "Invalid original hugepage overcommit limit: "
                            f"{original_hugepage_value!r}"
                        )
                    changed_hugepage_value = True
                    # The upstream prerequisite caps surplus hugepages at 8 GiB;
                    # it is not an immediate memory reservation.
                    setup.append(f"echo 4096 > {shlex.quote(hugepage_path)}")
                if setup:
                    self.node.execute(
                        " && ".join(setup),
                        shell=True,
                        sudo=True,
                        expected_exit_code=0,
                        expected_exit_code_failure_message=(
                            "failed native VMM host preparation"
                        ),
                    )
                if configuration != CONFIGURATIONS[2]:
                    vsock_check = self._wrap_command_for_group(
                        f"test -r {vsock} && test -w {vsock}"
                    )
                    access = self.node.execute(
                        vsock_check,
                        shell=True,
                        expected_exit_code=None,
                        no_info_log=True,
                        no_error_log=True,
                    )
                    if access.exit_code:
                        cast(Posix, self.node.os).install_packages(["acl"])
                        original_vsock_acl = self.node.execute(
                            f"getfacl -cp {shlex.quote(vsock)}",
                            shell=True,
                            sudo=True,
                            expected_exit_code=0,
                            expected_exit_code_failure_message=(
                                "failed to preserve existing vhost-vsock ACL"
                            ),
                        ).stdout.strip()
                        acl_user = self.node.execute(
                            "id -un",
                            shell=True,
                            expected_exit_code=0,
                            expected_exit_code_failure_message=(
                                "failed to identify the OpenVMM test user"
                            ),
                        ).stdout.strip()
                        if not acl_user or not original_vsock_acl:
                            raise LisaException(
                                "Could not safely prepare restricted vhost-vsock access"
                            )
                        self.node.execute(
                            f"setfacl -m "
                            f"{shlex.quote(f'u:{acl_user}:rw')} {shlex.quote(vsock)}",
                            shell=True,
                            sudo=True,
                            expected_exit_code=0,
                            expected_exit_code_failure_message=(
                                "failed to grant temporary vhost-vsock access"
                            ),
                        )

            checks = [f"test -r {device} && test -w {device}"]
            if configuration != CONFIGURATIONS[2]:
                checks.append(f"test -r {vsock} && test -w {vsock}")
            if configuration == CONFIGURATIONS[1]:
                # Upstream's 4096-page threshold is an 8 GiB surplus-page cap,
                # not an immediate memory reservation.
                checks.append(f'test "$(cat {shlex.quote(hugepage_path)})" -ge 4096')
            self.node.execute(
                self._wrap_command_for_group(" && ".join(checks)),
                shell=True,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    "native VMM host prerequisites are unmet"
                ),
            )
            if configuration != CONFIGURATIONS[2]:
                images = IMAGES + (
                    ARM_IMAGES if configuration == CONFIGURATIONS[1] else ()
                )
                for filename, size in images:
                    path = shlex.quote(str(content / "images" / filename))
                    url = shlex.quote(
                        "https://hvlitetestvhds.blob.core.windows.net/vhds/" + filename
                    )
                    self._run_logged_command(
                        name=f"openvmm_download_{filename}",
                        command=(
                            f"if ! test -f {path} || "
                            f'test "$(stat -c %s {path})" -ne {size}; then '
                            f"curl --fail --location --retry 3 {url} -o {path}; fi && "
                            f'test "$(stat -c %s {path})" -eq {size}'
                        ),
                        log_path=log_path,
                        timeout=self.RESTORE_TIMEOUT,
                        update_envs=env,
                    )
            yield
        finally:
            has_error = sys.exc_info()[0] is not None
            cleanup_errors = []
            if acl_user and original_vsock_acl is not None:
                restore_acl = (
                    f"printf '%s\\n' {shlex.quote(original_vsock_acl)} | "
                    f"setfacl --set-file=- {shlex.quote(vsock)}"
                )
                try:
                    result = self.node.execute(
                        restore_acl,
                        shell=True,
                        sudo=True,
                        expected_exit_code=None,
                        no_info_log=True,
                    )
                    if result.exit_code:
                        cleanup_errors.append("failed to restore vhost-vsock ACL")
                except Exception as error:
                    cleanup_errors.append(f"failed to restore vhost-vsock ACL: {error}")
            if changed_hugepage_value and original_hugepage_value is not None:
                try:
                    result = self.node.execute(
                        f"echo {shlex.quote(original_hugepage_value)} > "
                        f"{shlex.quote(hugepage_path)}",
                        shell=True,
                        sudo=True,
                        expected_exit_code=None,
                        no_info_log=True,
                    )
                    if result.exit_code:
                        cleanup_errors.append(
                            "failed to restore hugepage overcommit limit"
                        )
                except Exception as error:
                    cleanup_errors.append(
                        f"failed to restore hugepage overcommit limit: {error}"
                    )
            if cleanup_errors:
                self.node.mark_dirty()
                self._log.error("; ".join(cleanup_errors))
                if not has_error:
                    raise LisaException("; ".join(cleanup_errors))

    def _collect_native_results(self, log_path: Path, junit: Path) -> None:
        self._copy_back_if_exists(self.repo_root / "target/nextest/ci/junit.xml", junit)
        remote_archive = self.repo_root / "diagnostics.tar.gz"
        result = self.node.execute(
            f"tar -czf {shlex.quote(str(remote_archive))} "
            f"-C {shlex.quote(str(self.repo_root))} "
            "logs $(for d in flow test/test_results input/test_results; do "
            'if test -d "$d"; then printf \'%s\\n\' "$d"; fi; done)',
            cwd=self.repo_root,
            shell=True,
            expected_exit_code=None,
        )
        if result.exit_code:
            self._log.warning(
                f"failed to archive native OpenVMM diagnostics: {result.stderr}"
            )
        self._copy_back_if_exists(
            remote_archive, log_path / "openvmm_vmm_tests_artifacts.tar.gz"
        )

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        self._set_repo_paths()
        self._prepared_ref = None
        self._repo_prepared = False

    def run_vmm_tests_prebuilt_binary(
        self,
        log_path: Path,
        binary_path: str,
        ref: str = "",
        release: bool = False,
        test_filter: str = "",
        install_missing_deps: bool = True,
        skip_vhd_prompt: bool = True,
    ) -> _JUnitSummary:
        if not binary_path or not PurePath(binary_path).is_absolute():
            raise LisaException(
                "openvmm_prebuilt_binary_path must explicitly name an absolute "
                "path to the packaged OpenVMM executable."
            )
        _cache_vmm_version_in_node(self.node, "UNKNOWN")
        node_os = cast(Posix, self.node.os)
        if not node_os.package_exists("openvmm"):
            if not node_os.is_package_in_repo("openvmm"):
                raise SkippedException(
                    "The openvmm RPM is not installed and is unavailable in the "
                    "configured OS package repositories."
                )
            self._log.info(
                "Installing the prebuilt OpenVMM package from the OS repository"
            )
            node_os.install_packages("openvmm")
        original_identity = self._get_prebuilt_binary_identity(binary_path)
        output_dir: Optional[PurePath] = None
        output_storage_dir: Optional[PurePath] = None
        try:
            ref, ref_source = self._resolve_prebuilt_tests_ref(ref)
            env = self._prepare_repo(log_path, ref)
            working_path = str(self.node.working_path).rstrip("/")
            output_storage_dir = self.node.get_pure_path(
                self.node.execute(
                    f"mktemp -d {shlex.quote(working_path)}/ovmm-XXXXXXXX",
                    shell=True,
                    expected_exit_code=0,
                    expected_exit_code_failure_message=(
                        "failed to create an OpenVMM test output directory on "
                        "the configured working volume"
                    ),
                ).stdout.strip()
            )
            # Keep Petri's socket paths short while all large outputs remain on
            # the configured working volume.
            output_dir = self._create_short_temp_path(output_storage_dir)
            self._log.info(f"Prebuilt OpenVMM test output directory: {output_dir}")
            command = [
                self.node.tools[Cargo].command,
                "xflowey",
                "vmm-tests-run",
                "--target",
                "linux-x64",
                "--dir",
                str(output_dir),
                "--build-only",
                "--ci-profile",
            ]
            if install_missing_deps:
                command.append("--install-missing-deps")
            if skip_vhd_prompt:
                command.append("--skip-vhd-prompt")
            if release:
                command.append("--release")
            if test_filter:
                command.extend(["--filter", test_filter])
            self._run_logged_command(
                name="openvmm_prebuilt_prepare",
                command=shlex.join(command),
                log_path=log_path,
                timeout=self.VMM_TIMEOUT,
                update_envs=env,
            )
            self._select_prebuilt_binary(original_identity[0], output_dir)
            remote_junit = output_dir / "target" / "nextest" / "ci" / "junit.xml"
            self.node.execute(
                f"test -f {shlex.quote(str(output_dir / 'run.sh'))} && "
                f"rm -f -- {shlex.quote(str(remote_junit))}",
                shell=True,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    "Flowey build-only preparation did not produce the test launcher"
                ),
            )
            self._record_prebuilt_test_details(
                log_path, binary_path, original_identity, ref, ref_source
            )
            name = "openvmm_vmm_tests_prebuilt_binary"
            local_junit = log_path / f"{name}.junit.xml"
            local_junit.unlink(missing_ok=True)
            try:
                self._run_logged_command(
                    name=name,
                    command=self._wrap_command_for_group(
                        f"bash {shlex.quote(str(output_dir / 'run.sh'))}"
                    ),
                    log_path=log_path,
                    timeout=self.VMM_TIMEOUT,
                    update_envs=env,
                    artifact_dir=output_dir / "test_results",
                )
            finally:
                self._copy_back_if_exists(remote_junit, local_junit)
            if not local_junit.exists():
                raise LisaException(
                    "Prebuilt OpenVMM validation requires a fresh nextest JUnit "
                    "report; check harness compatibility and artifact copy-back."
                )
            summary = self._check_vmm_tests_results(
                name, log_path / f"{name}.log", local_junit
            )
            if not summary.passed_tests:
                raise LisaException(
                    "Prebuilt OpenVMM validation executed no passing tests. "
                    "An empty or entirely ignored selection is not validation."
                )
            return summary
        finally:
            try:
                if self._get_prebuilt_binary_identity(binary_path) != original_identity:
                    raise LisaException(
                        "The selected prebuilt OpenVMM binary path or SHA256 changed "
                        "during validation."
                    )
            finally:
                if output_dir is not None or output_storage_dir is not None:
                    # Preserve the original test error if cleanup also fails.
                    has_error = sys.exc_info()[0] is not None
                    cleanup_errors = []
                    if output_dir is not None:
                        try:
                            if not re.fullmatch(
                                r"/tmp/ovi-[A-Za-z0-9]{8}", str(output_dir)
                            ):
                                raise LisaException(
                                    f"Refusing to remove unexpected temporary path: "
                                    f"{output_dir}"
                                )
                            self.node.execute(
                                f"rm -f -- {shlex.quote(str(output_dir))}",
                                shell=True,
                                expected_exit_code=0,
                                expected_exit_code_failure_message=(
                                    f"failed to remove OpenVMM temporary path: "
                                    f"{output_dir}"
                                ),
                            )
                        except (AssertionError, LisaException, OSError) as error:
                            cleanup_errors.append(str(error))
                    if output_storage_dir is not None:
                        try:
                            if not str(output_storage_dir).startswith(
                                f"{working_path}/ovmm-"
                            ):
                                raise LisaException(
                                    "Refusing to remove unexpected OpenVMM "
                                    f"working directory: {output_storage_dir}"
                                )
                            self.node.execute(
                                f"rm -rf -- {shlex.quote(str(output_storage_dir))}",
                                shell=True,
                                expected_exit_code=0,
                                expected_exit_code_failure_message=(
                                    "failed to remove OpenVMM test directory: "
                                    f"{output_storage_dir}"
                                ),
                            )
                        except (AssertionError, LisaException, OSError) as error:
                            cleanup_errors.append(str(error))
                    if cleanup_errors:
                        self._log.error(
                            "OpenVMM test directory cleanup failed: "
                            + "; ".join(cleanup_errors)
                        )
                        if not has_error:
                            raise LisaException("; ".join(cleanup_errors))

    def _resolve_prebuilt_tests_ref(self, ref: str) -> Tuple[str, str]:
        if ref.strip():
            self._log.info(f"Using explicit OpenVMM harness reference: {ref.strip()}")
            return ref.strip(), "explicit"

        version = self.node.execute(
            "rpm -q --queryformat '%{VERSION}' openvmm",
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "failed to query the installed OpenVMM RPM version"
            ),
        ).stdout.strip()
        if not re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z.+_~-]*", version):
            raise LisaException(f"Invalid installed OpenVMM RPM version: {version!r}")

        tag = f"openvmm-v{version}"
        tag_ref = f"refs/tags/{tag}"
        parameters: List[str] = []
        if self.auth_token:
            parameters.extend(
                ["-c", f"http.extraheader=AUTHORIZATION: bearer {self.auth_token}"]
            )
        parameters.extend(
            ["ls-remote", "--exit-code", "--tags", "--refs", self.repo_url, tag_ref]
        )
        result = self.node.tools[Git].run(
            shlex.join(parameters),
            shell=True,
            force_run=True,
            update_envs={"GIT_TERMINAL_PROMPT": "0"},
            timeout=120,
        )
        if result.exit_code == 2:
            self._log.info(
                f"No upstream tag {tag} found for installed OpenVMM RPM {version}; "
                "using main for the harness. The latest harness may be incompatible "
                "with this package."
            )
            return "main", "missing-package-tag"
        result.assert_exit_code(
            message=(
                f"Failed to look up OpenVMM harness tag {tag}: "
                f"stdout={result.stdout}\nstderr={result.stderr}"
            )
        )
        if not re.fullmatch(
            rf"[0-9a-f]{{40,64}}\s+{re.escape(tag_ref)}", result.stdout.strip()
        ):
            raise LisaException(
                f"Unexpected response looking up OpenVMM harness tag {tag}: "
                f"stdout={result.stdout}\nstderr={result.stderr}"
            )
        self._log.info(
            f"Selected OpenVMM harness tag {tag} for installed RPM version {version}"
        )
        return tag, "package-version"

    def _get_prebuilt_binary_identity(self, binary_path: str) -> Tuple[str, str]:
        if not binary_path or not PurePath(binary_path).is_absolute():
            raise LisaException(
                "openvmm_prebuilt_binary_path must explicitly name an absolute "
                "path to an installed OpenVMM executable."
            )
        quoted_path = shlex.quote(binary_path)
        resolved_path = self.node.execute(
            f"test -f {quoted_path} && test -x {quoted_path} && "
            f"readlink -f -- {quoted_path}",
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                f"Prebuilt OpenVMM executable is missing or not executable: "
                f"{binary_path}. No source-build fallback is permitted."
            ),
        ).stdout.strip()
        checksum_output = self.node.execute(
            f"sha256sum -- {shlex.quote(resolved_path)}",
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="failed to hash prebuilt OpenVMM",
        ).stdout.split()
        if not checksum_output or not re.fullmatch(r"[0-9a-f]{64}", checksum_output[0]):
            raise LisaException("Invalid SHA256 output for the prebuilt OpenVMM binary")
        return resolved_path, checksum_output[0]

    def _select_prebuilt_binary(self, binary_path: str, content_dir: PurePath) -> None:
        # Petri checks these content paths before falling back to Cargo outputs.
        commands = []
        for target in ("x86_64-unknown-linux-gnu", "x86_64-unknown-linux-musl"):
            directory = content_dir / target
            commands.extend(
                [
                    f"mkdir -p {shlex.quote(str(directory))}",
                    f"ln -sfnT -- {shlex.quote(binary_path)} "
                    f"{shlex.quote(str(directory / 'openvmm'))}",
                    f"test {shlex.quote(binary_path)} -ef "
                    f"{shlex.quote(str(directory / 'openvmm'))}",
                ]
            )
        self.node.execute(
            " && ".join(commands),
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "failed to replace Flowey's staged OpenVMM with the packaged binary"
            ),
        )

    def _record_prebuilt_test_details(
        self,
        log_path: Path,
        binary_path: str,
        identity: Tuple[str, str],
        ref: str,
        ref_source: str,
    ) -> None:
        version = self._record_vmm_version(identity[0])
        package = self.node.execute(
            f"rpm -qf -- {shlex.quote(identity[0])}",
            shell=True,
            expected_exit_code=None,
        )
        provenance = {
            "binary_path": binary_path,
            "resolved_binary_path": identity[0],
            "sha256": identity[1],
            "binary_version": version,
            "rpm_query_exit_code": package.exit_code,
            "rpm_query_stdout": package.stdout,
            "rpm_query_stderr": package.stderr,
            "host_os": str(self.node.os.information),
            "host_kernel": self.node.tools[Uname]
            .get_linux_information()
            .kernel_version_raw,
            "harness_ref": ref,
            "harness_ref_source": ref_source,
            "harness_sha": self.node.tools[Git].get_current_commit_hash(self.repo_root),
        }
        rendered = json.dumps(provenance, indent=2)
        self._log.info(f"Prebuilt OpenVMM validation provenance:\n{rendered}")
        (log_path / "openvmm_prebuilt_provenance.json").write_text(
            rendered + "\n", encoding="utf-8"
        )

    def _record_vmm_version(self, binary_path: str) -> str:
        # A host may also have Cloud Hypervisor installed; never report its version.
        _cache_vmm_version_in_node(self.node, "UNKNOWN")
        result = self.node.execute(
            f"{shlex.quote(binary_path)} --version",
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                f"failed to query OpenVMM version from {binary_path}"
            ),
        )
        output = self._ANSI_ESCAPE_PATTERN.sub("", result.stdout).strip()
        # Real --version output has a banner followed by build details; splitlines
        # handles both LF and SSH CRLF without treating those details as the banner.
        match = VERSION_PATTERN.fullmatch(output.splitlines()[0]) if output else None
        if not match or not match.group("version").strip():
            raise LisaException(
                f"Invalid OpenVMM version output from {binary_path}: {output!r}"
            )
        version = match.group("version").strip()
        _cache_vmm_version_in_node(self.node, version)
        self._log.info(f"OpenVMM version: {version} (binary: {binary_path})")
        return version

    def _get_repo_dir_name(self) -> str:
        repo_hash = hashlib.sha256(self.repo_url.encode("utf-8")).hexdigest()[:8]
        return f"openvmm-{repo_hash}"

    def _set_repo_paths(self) -> None:
        self.repo_root = self.get_tool_path(use_global=True) / self._get_repo_dir_name()
        self._artifact_root = self.repo_root / "target" / "lisa-openvmm-tests"

    def _install(self) -> bool:
        node_os = cast(Posix, self.node.os)
        package_names = self._distro_package_mapping.get(type(node_os).__name__)
        if not package_names:
            raise UnsupportedDistroException(
                node_os,
                "OpenVMM upstream tests are not supported on this distro.",
            )

        node_os.install_packages(package_names)

        self._set_repo_paths()

        self.repo_root = self.node.tools[Git].clone(
            url=self.repo_url,
            cwd=self.get_tool_path(use_global=True),
            dir_name=self._get_repo_dir_name(),
            fail_on_exists=False,
            auth_token=self.auth_token or None,
            timeout=1800,
        )
        self.node.execute(
            f"mkdir -p {shlex.quote(str(self._artifact_root))}",
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "failed to create OpenVMM upstream test artifact directory"
            ),
        )

        return self.node.tools[Ls].path_exists(str(self.repo_root))

    def _prepare_repo(self, log_path: Path, ref: str) -> Dict[str, str]:
        git = self.node.tools[Git]
        if not self._check_exists() and not self._install():
            raise LisaException(
                f"failed to prepare OpenVMM upstream tests repository from "
                f"{self.repo_url}"
            )

        cargo_env = self._get_cargo_environment()
        if ref and self._prepared_ref != ref:
            git.checkout(ref, self.repo_root)
            self.node.execute(
                "git submodule update --init --recursive",
                shell=True,
                cwd=self.repo_root,
                update_envs=cargo_env,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    f"failed to update submodules after checking out {ref}"
                ),
            )
            self._repo_prepared = False

        openvmm_commit = git.get_current_commit_hash(self.repo_root).strip()
        self._log.info(
            f"OpenVMM upstream tests repository: {self.repo_url}, "
            f"requested ref: {ref or '<default>'}, HEAD: {openvmm_commit}"
        )

        if not self._repo_prepared:
            self._restore_packages(log_path, cargo_env)
            self._repo_prepared = True
            self._prepared_ref = ref or ""

        self._ensure_cargo_nextest(log_path, cargo_env)

        return cargo_env

    def _restore_packages(
        self, log_path: Path, env: Dict[str, str], include_emulated: bool = False
    ) -> None:
        command = [
            self.node.tools[Cargo].command,
            "xflowey",
            "restore-packages",
            "--no-compat-igvm",
        ]
        if include_emulated:
            command.extend(["x86-64", "aarch64"])
        self._run_logged_command(
            name="openvmm_restore_packages",
            command=shlex.join(command),
            log_path=log_path,
            timeout=self.RESTORE_TIMEOUT,
            update_envs=env,
        )

    def _get_cargo_environment(self) -> Dict[str, str]:
        cargo = self.node.tools[Cargo]
        home_dir = self.node.execute(
            "echo $HOME",
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "failed to determine the home directory for OpenVMM tests"
            ),
        ).stdout.strip()
        # Fetch the current remote PATH explicitly so we can prepend to a
        # concrete value rather than relying on shell expansion in update_envs.
        current_env_path = self.node.execute(
            "echo $PATH",
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "failed to determine the remote PATH for OpenVMM tests"
            ),
        ).stdout.strip()
        cargo_bin_dir = ""
        cargo_command = cargo.command
        if not PurePath(cargo_command).is_absolute():
            # cargo.command is a bare name on PATH; resolve its real location
            # so we can build correct RUSTC/RUSTDOC paths.
            resolve_result = self.node.execute(
                f"command -v {shlex.quote(cargo_command)}",
                shell=True,
                expected_exit_code=None,
            )
            if resolve_result.exit_code == 0:
                cargo_command = resolve_result.stdout.strip()
        if cargo_command and PurePath(cargo_command).is_absolute():
            cargo_bin_dir = str(PurePath(cargo_command).parent)
        cargo_home_bin = f"{home_dir}/.cargo/bin"
        rustup_bin = f"{cargo_home_bin}/rustup"
        toolchain = cargo.toolchain or "stable"

        self.node.execute(
            "mkdir -p ~/.rustup/downloads ~/.rustup/tmp ~/.cargo/bin",
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "failed to prepare rustup directories for OpenVMM tests"
            ),
        )
        self.node.execute(
            f"{shlex.quote(rustup_bin)} component add rust-src --toolchain "
            f"{shlex.quote(toolchain)}",
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "failed to install the rust-src component for OpenVMM tests"
            ),
        )

        path_prefix = (
            f"{cargo_home_bin}:{cargo_bin_dir}" if cargo_bin_dir else cargo_home_bin
        )
        env: Dict[str, str] = {
            "OPENSSL_NO_VENDOR": "1",
            "PATH": f"{path_prefix}:{current_env_path}",
            "RUST_BACKTRACE": "full",
            "RUST_LOG": "info",
        }
        if cargo_bin_dir:
            env["RUSTC"] = f"{cargo_bin_dir}/rustc"
            env["RUSTDOC"] = f"{cargo_bin_dir}/rustdoc"
        return env

    def _wrap_command_for_group(self, command: str) -> str:
        group = str(self.command_group).strip()
        if not group:
            return command
        return f"sg {shlex.quote(group)} -c {shlex.quote(command)}"

    def _run_logged_command(
        self,
        name: str,
        command: str,
        log_path: Path,
        timeout: int,
        update_envs: Dict[str, str],
        artifact_dir: Optional[PurePath] = None,
        sudo: bool = False,
    ) -> None:
        remote_log = self._artifact_root / f"{name}.log"
        self.node.execute(
            f": > {shlex.quote(str(remote_log))}",
            shell=True,
            cwd=self.repo_root,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                f"failed to create command log as checkout owner: {remote_log}"
            ),
        )
        command_result = self.node.execute(
            (
                "bash -lc "
                + shlex.quote(
                    "set -o pipefail; "
                    f"{{ {command}; }} > {shlex.quote(str(remote_log))} 2>&1"
                )
            ),
            shell=True,
            sudo=sudo,
            cwd=self.repo_root,
            timeout=timeout,
            update_envs=update_envs,
            expected_exit_code=None,
        )

        self._copy_back_if_exists(remote_log, log_path / f"{name}.log")

        if artifact_dir:
            remote_archive = self._artifact_root / f"{name}_artifacts.tar.gz"
            self._archive_remote_directory(artifact_dir, remote_archive)
            self._copy_back_if_exists(
                remote_archive,
                log_path / f"{name}_artifacts.tar.gz",
            )

        if command_result.exit_code == 0:
            return

        timed_out = getattr(command_result, "is_timeout", False)
        tail_output = self._tail_remote_log(remote_log)
        if timed_out:
            raise LisaException(
                f"{name} timed out after {timeout} seconds. "
                f"Last log lines: {tail_output}"
            )

        raise LisaException(
            f"{name} failed with exit code {command_result.exit_code}. "
            f"Last log lines: {tail_output}"
        )

    def _ensure_cargo_nextest(
        self,
        log_path: Path,
        update_envs: Dict[str, str],
        install_missing_deps: bool = True,
    ) -> None:
        version = self._get_nextest_version()
        if self._has_cargo_nextest(update_envs, version):
            return
        if not install_missing_deps:
            raise LisaException(
                f"cargo-nextest {version} must be installed. Enable "
                "openvmm_vmm_tests_install_missing_deps to install the pinned "
                "standalone binary, or install that exact version manually."
            )

        self._log.debug(
            f"cargo-nextest {version} was not available; "
            "installing the upstream pinned standalone binary"
        )
        install_dir = self._artifact_root / "cargo-nextest-install"
        release_name = f"cargo-nextest-{version}"
        asset_name = f"{release_name}-{self.NEXTEST_LINUX_X64_TARGET}"
        archive_name = f"{asset_name}.tar.gz"
        sha256_name = f"{asset_name}.sha256"
        release_url = (
            "https://github.com/nextest-rs/nextest/releases/download/" f"{release_name}"
        )
        download_url = f"{release_url}/{archive_name}"
        sha256_url = f"{release_url}/{sha256_name}"
        curl_command = self.node.tools[Curl].command
        install_command = (
            f"rm -rf {shlex.quote(str(install_dir))} && "
            f"mkdir -p {shlex.quote(str(install_dir))} ~/.cargo/bin && "
            f"cd {shlex.quote(str(install_dir))} && "
            f"{shlex.quote(curl_command)} --fail -L {shlex.quote(download_url)} "
            f"-o {shlex.quote(archive_name)} && "
            f"{shlex.quote(curl_command)} --fail -L {shlex.quote(sha256_url)} "
            f"-o {shlex.quote(sha256_name)} && "
            f"computed=$(sha256sum {shlex.quote(archive_name)} | "
            "awk '{print $1}') && "
            f"expected=$(awk '{{print $1}}' {shlex.quote(sha256_name)}) && "
            'test "$computed" = "$expected" || '
            '{ echo "SHA256 mismatch: expected=$expected '
            'computed=$computed" >&2; exit 1; } && '
            f"tar -xf {shlex.quote(archive_name)} && "
            "cp cargo-nextest ~/.cargo/bin/cargo-nextest && "
            "chmod 0755 ~/.cargo/bin/cargo-nextest"
        )
        self._run_logged_command(
            name="openvmm_install_cargo_nextest",
            command=install_command,
            log_path=log_path,
            timeout=self.RESTORE_TIMEOUT,
            update_envs=update_envs,
        )

        if not self._has_cargo_nextest(update_envs, version):
            raise LisaException(
                "cargo-nextest is still unavailable after the fallback install. "
                "See openvmm_install_cargo_nextest.log for details."
            )

    def _get_nextest_version(self) -> str:
        # Follow upstream's runner pin rather than a fixed LISA nextest version.
        result = self.node.execute(
            "cat flowey/flowey_lib_hvlite/src/_jobs/cfg_versions.rs",
            shell=True,
            cwd=self.repo_root,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "failed to read the upstream cargo-nextest version pin"
            ),
            no_info_log=True,
        )
        match = re.search(
            r'pub const NEXTEST:\s*&str\s*=\s*"(?P<version>\d+\.\d+\.\d+)";',
            result.stdout,
        )
        if not match:
            raise LisaException(
                "The OpenVMM checkout has no recognized cargo-nextest version pin "
                "in flowey/flowey_lib_hvlite/src/_jobs/cfg_versions.rs"
            )
        return match.group("version")

    def _has_cargo_nextest(self, update_envs: Dict[str, str], version: str) -> bool:
        result = self.node.execute(
            "cargo nextest --version",
            shell=True,
            cwd=self.repo_root,
            update_envs=update_envs,
            expected_exit_code=None,
            no_info_log=True,
            no_error_log=True,
        )
        return result.exit_code == 0 and bool(
            re.search(
                rf"\bcargo-nextest {re.escape(version)}(?:\s|$)",
                f"{result.stdout}\n{result.stderr}",
            )
        )

    def _archive_remote_directory(
        self,
        source_dir: PurePath,
        archive_path: PurePath,
    ) -> None:
        result = self.node.execute(
            (
                f"rm -f {shlex.quote(str(archive_path))} && "
                f"tar -czf {shlex.quote(str(archive_path))} "
                f"-C {shlex.quote(str(source_dir))} ."
            ),
            shell=True,
            expected_exit_code=None,
            no_info_log=True,
            no_error_log=True,
        )
        if result.exit_code != 0:
            self._log.warning(
                f"failed to archive '{source_dir}' to '{archive_path}' "
                f"(exit {result.exit_code}); diagnostic artifacts may be missing"
            )

    def _copy_back_if_exists(self, remote_path: PurePath, local_path: Path) -> None:
        if not self.node.tools[Ls].path_exists(str(remote_path)):
            self._log.debug(f"artifact not present on remote, skipping: {remote_path}")
            return
        try:
            self.node.shell.copy_back(remote_path, local_path)
        except OSError as identifier:
            self._log.debug(
                f"failed to copy artifact {remote_path} to {local_path}: {identifier}"
                " (check permissions, disk space, and SSH/SFTP connectivity)"
            )

    def _tail_remote_log(self, remote_log: PurePath) -> str:
        result = self.node.execute(
            f"tail -n 200 {shlex.quote(str(remote_log))}",
            shell=True,
            expected_exit_code=None,
            no_info_log=True,
            no_error_log=True,
        )
        output = (result.stdout or result.stderr).strip()
        return output[-4000:] if output else "no log output captured"

    def _check_vmm_tests_results(
        self,
        name: str,
        log_file: Path,
        junit_file: Optional[Path],
    ) -> _JUnitSummary:
        # Reject missing, empty or inconsistent results instead of assuming success.
        summary: Optional[_JUnitSummary] = None
        if junit_file and junit_file.exists():
            try:
                summary = self._parse_junit_summary(junit_file)
            except (ETree.ParseError, ValueError) as identifier:
                raise LisaException(
                    f"{name} produced an unreadable JUnit report at {junit_file}: "
                    f"{identifier}"
                ) from identifier

            if summary.failures or summary.errors:
                raise LisaException(
                    f"{name} reported test failures.\n"
                    f"{self.format_run_summary(summary)}"
                )
        if log_file.exists():
            log_summary = self._extract_log_summary(log_file)
            failure_summary = self._extract_failure_summary_from_log(
                log_file, log_summary
            )
            if failure_summary:
                raise LisaException(
                    f"{name} reported test failures.\n{failure_summary}"
                )

            # Nextest's JUnit omits filtered tests. Its terminal summary retains them.
            if log_summary.has_nextest_summary:
                if summary and (
                    summary.tests != log_summary.tests
                    or summary.passed != log_summary.passed
                ):
                    raise LisaException(
                        f"{name} produced conflicting JUnit and nextest "
                        "execution counts. Check that both reports are complete "
                        "and belong to the same run."
                    )
                if summary:
                    log_summary.passed_tests = self._deduplicate_test_names(
                        log_summary.passed_tests + summary.passed_tests
                    )
                summary = log_summary

        if summary is None:
            raise LisaException(
                f"{name} did not produce a recognized nextest summary or JUnit "
                f"report. Checked JUnit path: {junit_file}, log path: {log_file}. "
                "Verify the test run completed and artifact copy-back succeeded."
            )
        if summary.tests <= 0:
            raise LisaException(
                f"{name} executed no tests. Check the nextest filter and test assets.\n"
                f"{self.format_run_summary(summary)}"
            )
        if summary.passed != summary.tests or (
            summary.total and summary.tests != summary.total
        ):
            raise LisaException(
                f"{name} produced incomplete or inconsistent test results.\n"
                f"{self.format_run_summary(summary)}"
            )
        return summary

    def format_run_summary(
        self,
        summary: _JUnitSummary,
        include_passed: bool = True,
        include_failed: bool = True,
        max_items: int = 20,
    ) -> str:
        failed_count = summary.failures + summary.errors
        if not failed_count and summary.failed_tests:
            failed_count = len(summary.failed_tests)

        if summary.passed:
            passed_count = summary.passed
        elif summary.passed_tests:
            passed_count = len(summary.passed_tests)
        elif summary.tests:
            # Derive passed count from totals when individual names aren't captured
            # (e.g. JUnit reports that record counts but omit per-case elements).
            passed_count = max(0, summary.tests - summary.failures - summary.errors)
        else:
            passed_count = 0
        tests_run = summary.tests or (passed_count + failed_count)
        if summary.total:
            overview = (
                f"{tests_run}/{summary.total} tests run: "
                f"{passed_count} passed, {failed_count} failed, "
                f"{summary.skipped} skipped"
            )
        else:
            overview = (
                f"{tests_run} tests run: {passed_count} passed, "
                f"{failed_count} failed, {summary.skipped} skipped"
            )

        lines = [overview]
        if include_passed and (passed_count or summary.passed_tests):
            lines.append("Passed tests:")
            lines.append(
                self._summarize_test_names(
                    summary.passed_tests,
                    max_items=max_items,
                    empty_message="  - no passing test names captured",
                )
            )
        if include_failed and (failed_count or summary.failed_tests):
            lines.append("Failed tests:")
            lines.append(
                self._summarize_test_names(
                    summary.failed_tests,
                    max_items=max_items,
                    empty_message="  - no failing test names captured",
                )
            )

        return "\n".join(lines)

    def _parse_junit_summary(self, junit_file: Path) -> _JUnitSummary:
        tree = ETree.parse(junit_file)
        root = tree.getroot()
        summary = _JUnitSummary()

        suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
        if not suites:
            suites = [root]

        for suite in suites:
            for attribute in ("tests", "failures", "errors", "skipped", "disabled"):
                value = suite.get(attribute)
                if value is not None and not value.isdigit():
                    raise LisaException(
                        f"Invalid JUnit {attribute} count {value!r} in {junit_file}"
                    )
            summary.tests += int(suite.attrib.get("tests", "0"))
            summary.failures += int(suite.attrib.get("failures", "0"))
            summary.errors += int(suite.attrib.get("errors", "0"))
            summary.skipped += int(
                suite.attrib.get("skipped", suite.attrib.get("disabled", "0"))
            )

        has_failed_testcase = False
        for testcase in root.iter("testcase"):
            classname = testcase.attrib.get("classname", "").strip()
            test_name = testcase.attrib.get("name", "").strip()
            full_name = self._format_test_name(classname, test_name)

            if testcase.find("failure") is None and testcase.find("error") is None:
                if testcase.find("skipped") is None and full_name:
                    summary.passed_tests.append(full_name)
                continue

            has_failed_testcase = True
            if full_name:
                summary.failed_tests.append(full_name)

        summary.passed_tests = self._deduplicate_test_names(summary.passed_tests)
        summary.failed_tests = self._deduplicate_test_names(summary.failed_tests)
        summary.tests -= summary.skipped
        if has_failed_testcase and not (summary.failures or summary.errors):
            raise LisaException(
                f"Inconsistent JUnit failure elements in {junit_file}: "
                "testcase failures or errors are present but suite counts report none"
            )
        summary.passed = summary.tests - summary.failures - summary.errors
        if summary.passed < 0:
            raise LisaException(
                f"Inconsistent JUnit counts in {junit_file}: "
                "failures, errors and skipped exceed the total test count"
            )

        return summary

    def _extract_log_summary(self, log_file: Path) -> _JUnitSummary:
        content = log_file.read_text(encoding="utf-8", errors="ignore")
        return self._extract_log_summary_from_content(content)

    def _extract_failure_summary_from_log(
        self,
        log_file: Path,
        summary: Optional[_JUnitSummary] = None,
    ) -> Optional[str]:
        content = self._strip_ansi_escape_sequences(
            log_file.read_text(encoding="utf-8", errors="ignore")
        )
        parsed_summary = summary or self._extract_log_summary_from_content(content)
        failed_count = parsed_summary.failures + parsed_summary.errors
        if not failed_count and parsed_summary.failed_tests:
            failed_count = len(parsed_summary.failed_tests)

        if failed_count:
            return self.format_run_summary(parsed_summary)

        lowered = content.lower()
        if (
            "encountered at least one test failure" in lowered
            or "encountered test failures." in lowered
        ):
            return "Log reported test failures without listing individual test names"

        return None

    def _extract_log_summary_from_content(self, content: str) -> _JUnitSummary:
        sanitized_content = self._strip_ansi_escape_sequences(content)
        summary = _JUnitSummary()
        summary_matches = list(self._SUMMARY_PATTERN.finditer(sanitized_content))
        if summary_matches:
            summary_match = summary_matches[-1]
            summary.has_nextest_summary = True
            summary.tests = int(summary_match.group("run"))
            summary.total = int(summary_match.group("total") or 0)
            counts = dict(
                (status, int(count))
                for count, status in re.findall(
                    r"\b(\d+) (passed|failed|skipped|timed out|exec failed|aborted)\b",
                    summary_match.group("counts"),
                )
            )
            summary.passed = counts.get("passed", 0)
            summary.failures = counts.get("failed", 0)
            summary.skipped = counts.get("skipped", 0)
            summary.errors = sum(
                counts.get(status, 0)
                for status in ("timed out", "exec failed", "aborted")
            )

        summary.passed_tests = self._deduplicate_test_names(
            self._PASSED_TEST_PATTERN.findall(sanitized_content)
        )
        summary.failed_tests = self._deduplicate_test_names(
            self._FAILED_TEST_PATTERN.findall(sanitized_content)
        )
        return summary

    def _deduplicate_test_names(self, test_names: List[str]) -> List[str]:
        normalized_names = [
            " ".join(test_name.split()) for test_name in test_names if test_name
        ]
        return list(dict.fromkeys(name for name in normalized_names if name))

    def _summarize_test_names(
        self,
        test_names: List[str],
        max_items: int = 20,
        empty_message: str = "  - no test names captured",
    ) -> str:
        names = self._deduplicate_test_names(test_names)
        if not names:
            return empty_message

        summarized_names = [f"  - {name}" for name in names[:max_items]]
        if len(names) > max_items:
            summarized_names.append(f"  - ... and {len(names) - max_items} more")
        return "\n".join(summarized_names)

    def _format_test_name(self, classname: str, test_name: str) -> str:
        if classname and test_name:
            return f"{classname} {test_name}"
        return test_name

    def _strip_ansi_escape_sequences(self, content: str) -> str:
        return self._ANSI_ESCAPE_PATTERN.sub("", content)
