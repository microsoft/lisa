# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
import shlex
import xml.etree.ElementTree as ETree
from dataclasses import dataclass, field
from pathlib import Path, PurePath
from typing import Any, Dict, List, Optional, Type, cast

from lisa.executable import Tool
from lisa.operating_system import CBLMariner, Posix, Ubuntu
from lisa.tools import Cargo, Curl, Git, Ls
from lisa.util import LisaException, UnsupportedDistroException


@dataclass
class _JUnitSummary:
    tests: int = 0
    total: int = 0
    passed: int = 0
    failures: int = 0
    errors: int = 0
    skipped: int = 0
    failed_tests: List[str] = field(default_factory=list)
    passed_tests: List[str] = field(default_factory=list)


class OpenVmmTests(Tool):
    RESTORE_TIMEOUT = 3600
    VMM_TIMEOUT = 43200
    NEXTEST_VERSION = "0.9.101"
    NEXTEST_LINUX_X64_TARGET = "x86_64-unknown-linux-gnu"
    _ANSI_ESCAPE_PATTERN = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
    _SUMMARY_PATTERN = re.compile(
        r"Summary \[\s*[\d.]+s\]\s+(?P<run>\d+)(?:/(?P<total>\d+))? tests run:\s+"
        r"(?P<passed>\d+) passed,\s+(?P<failed>\d+) failed,\s+"
        r"(?P<skipped>\d+) skipped"
    )
    _FAILED_TEST_PATTERN = re.compile(
        r"^\s*FAIL\s+\[[^\]]+\]\s+\S+\s+(?P<name>.+?)\s*$",
        re.MULTILINE,
    )
    _PASSED_TEST_PATTERN = re.compile(
        r"^\s*PASS\s+\[[^\]]+\]\s+\S+\s+(?P<name>.+?)\s*$",
        re.MULTILINE,
    )

    DEFAULT_REPO = "https://github.com/microsoft/openvmm.git"
    repo_url = DEFAULT_REPO
    auth_token = ""
    command_group = ""

    _distro_package_mapping = {
        Ubuntu.__name__: ["libssl-dev", "perl", "pkg-config"],
        CBLMariner.__name__: [
            "gcc",
            "openssl-devel",
            "perl",
            "pkg-config",
            "binutils",
            "glibc-devel",
        ],
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
        return [Git, Cargo, Curl]

    def _check_exists(self) -> bool:
        return self.node.tools[Ls].path_exists(str(self.repo_root))

    def run_vmm_tests(
        self,
        log_path: Path,
        ref: str = "",
        release: bool = False,
        test_filter: str = "",
        install_missing_deps: bool = True,
        skip_vhd_prompt: bool = True,
    ) -> _JUnitSummary:
        cargo = self.node.tools[Cargo]
        env = self._prepare_repo(log_path, ref)
        output_dir = self._artifact_root / "vmm-tests-run"
        self.node.execute(
            (
                f"rm -rf {shlex.quote(str(output_dir))} && "
                f"mkdir -p {shlex.quote(str(output_dir))}"
            ),
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "failed to prepare OpenVMM vmm-tests output directory"
            ),
        )

        command = [
            cargo.command,
            "xflowey",
            "vmm-tests-run",
            "--target",
            "linux-x64",
            "--dir",
            str(output_dir),
        ]
        if install_missing_deps:
            command.append("--install-missing-deps")
        if skip_vhd_prompt:
            command.append("--skip-vhd-prompt")
        if release:
            command.append("--release")
        if test_filter:
            command.extend(["--filter", test_filter])

        wrapped_command = self._wrap_command_for_group(shlex.join(command))

        self._run_logged_command(
            name="openvmm_vmm_tests",
            command=wrapped_command,
            log_path=log_path,
            timeout=self.VMM_TIMEOUT,
            update_envs=env,
        )

        local_junit = log_path / "openvmm_vmm_tests.junit.xml"
        self._copy_back_if_exists(output_dir / "junit.xml", local_junit)
        return self._check_vmm_tests_results(
            name="openvmm_vmm_tests",
            log_file=log_path / "openvmm_vmm_tests.log",
            junit_file=local_junit,
        )

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        tool_path = self.get_tool_path(use_global=True)
        self.repo_root = tool_path / "openvmm"
        self._artifact_root = self.repo_root / "target" / "lisa-openvmm-tests"
        self._prepared_ref = None
        self._repo_prepared = False

    def _install(self) -> bool:
        node_os = cast(Posix, self.node.os)
        package_names = self._distro_package_mapping.get(type(node_os).__name__)
        if not package_names:
            raise UnsupportedDistroException(
                node_os,
                "OpenVMM upstream tests are not supported on this distro.",
            )

        node_os.install_packages(package_names)

        self.repo_root = self.node.tools[Git].clone(
            url=self.repo_url,
            cwd=self.get_tool_path(use_global=True),
            dir_name="openvmm",
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
        cargo_env = self._get_cargo_environment()

        if ref and self._prepared_ref != ref:
            self.node.tools[Git].checkout(ref, self.repo_root)
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

        if not self._repo_prepared:
            restore_command = shlex.join(
                [
                    self.node.tools[Cargo].command,
                    "xflowey",
                    "restore-packages",
                    "--no-compat-igvm",
                ]
            )
            self._run_logged_command(
                name="openvmm_restore_packages",
                command=restore_command,
                log_path=log_path,
                timeout=self.RESTORE_TIMEOUT,
                update_envs=cargo_env,
            )
            self._repo_prepared = True
            self._prepared_ref = ref or ""

        self._ensure_cargo_nextest(log_path, cargo_env)

        return cargo_env

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
        cargo_bin_dir = str(PurePath(cargo.command).parent)
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

        return {
            "OPENSSL_NO_VENDOR": "1",
            "PATH": f"{cargo_home_bin}:{cargo_bin_dir}:$PATH",
            "RUST_BACKTRACE": "1",
            "RUSTC": f"{cargo_bin_dir}/rustc",
            "RUSTDOC": f"{cargo_bin_dir}/rustdoc",
            "RUST_LOG": "trace",
        }

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
    ) -> None:
        remote_log = self._artifact_root / f"{name}.log"
        command_result = self.node.execute(
            (
                "bash -lc "
                + shlex.quote(
                    f"set -o pipefail; {command} > {shlex.quote(str(remote_log))} 2>&1"
                )
            ),
            shell=True,
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
    ) -> None:
        if self._has_cargo_nextest(update_envs):
            return

        self._log.debug(
            "cargo-nextest was not available after restore-packages; "
            "installing the upstream pinned standalone binary"
        )
        install_dir = self._artifact_root / "cargo-nextest-install"
        archive_name = f"{self.NEXTEST_LINUX_X64_TARGET}.tar.gz"
        download_url = (
            f"https://get.nexte.st/{self.NEXTEST_VERSION}/"
            f"{self.NEXTEST_LINUX_X64_TARGET}.tar.gz"
        )
        curl_command = self.node.tools[Curl].command
        install_command = (
            f"rm -rf {shlex.quote(str(install_dir))} && "
            f"mkdir -p {shlex.quote(str(install_dir))} ~/.cargo/bin && "
            f"cd {shlex.quote(str(install_dir))} && "
            f"{shlex.quote(curl_command)} --fail -L {shlex.quote(download_url)} "
            f"-o {shlex.quote(archive_name)} && "
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

        if not self._has_cargo_nextest(update_envs):
            raise LisaException(
                "cargo-nextest is still unavailable after the fallback install. "
                "See openvmm_install_cargo_nextest.log for details."
            )

    def _has_cargo_nextest(self, update_envs: Dict[str, str]) -> bool:
        result = self.node.execute(
            "cargo nextest --version",
            shell=True,
            cwd=self.repo_root,
            update_envs=update_envs,
            expected_exit_code=None,
            no_info_log=True,
            no_error_log=True,
        )
        return result.exit_code == 0

    def _archive_remote_directory(
        self,
        source_dir: PurePath,
        archive_path: PurePath,
    ) -> None:
        self.node.execute(
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

    def _copy_back_if_exists(self, remote_path: PurePath, local_path: Path) -> None:
        try:
            self.node.shell.copy_back(remote_path, local_path)
        except Exception as identifier:
            self._log.debug(f"skipping artifact copy for {remote_path}: {identifier}")

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
        if junit_file and junit_file.exists():
            try:
                summary = self._parse_junit_summary(junit_file)
            except ETree.ParseError as identifier:
                raise LisaException(
                    f"{name} produced an unreadable JUnit report at {junit_file}: "
                    f"{identifier}"
                ) from identifier

            if summary.failures or summary.errors:
                raise LisaException(
                    f"{name} reported test failures.\n"
                    f"{self.format_run_summary(summary)}"
                )
            return summary

        if log_file.exists():
            summary = self._extract_log_summary(log_file)
            failure_summary = self._extract_failure_summary_from_log(log_file, summary)
            if failure_summary:
                raise LisaException(
                    f"{name} reported test failures.\n{failure_summary}"
                )

            return summary

        return _JUnitSummary()

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

        passed_count = summary.passed or len(summary.passed_tests)
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
            summary.tests += int(suite.attrib.get("tests", "0") or 0)
            summary.failures += int(suite.attrib.get("failures", "0") or 0)
            summary.errors += int(suite.attrib.get("errors", "0") or 0)
            summary.skipped += int(
                suite.attrib.get("skipped", suite.attrib.get("disabled", "0")) or 0
            )

        for testcase in root.iter("testcase"):
            classname = testcase.attrib.get("classname", "").strip()
            test_name = testcase.attrib.get("name", "").strip()
            full_name = self._format_test_name(classname, test_name)

            if testcase.find("failure") is None and testcase.find("error") is None:
                if testcase.find("skipped") is None and full_name:
                    summary.passed_tests.append(full_name)
                continue

            if full_name:
                summary.failed_tests.append(full_name)

        summary.passed_tests = self._deduplicate_test_names(summary.passed_tests)
        summary.failed_tests = self._deduplicate_test_names(summary.failed_tests)
        summary.passed = len(summary.passed_tests)

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
        summary_match = self._SUMMARY_PATTERN.search(sanitized_content)
        if summary_match:
            summary.tests = int(summary_match.group("run"))
            summary.total = int(summary_match.group("total") or 0)
            summary.passed = int(summary_match.group("passed"))
            summary.failures = int(summary_match.group("failed"))
            summary.skipped = int(summary_match.group("skipped"))

        summary.passed_tests = self._deduplicate_test_names(
            self._PASSED_TEST_PATTERN.findall(sanitized_content)
        )
        summary.failed_tests = self._deduplicate_test_names(
            self._FAILED_TEST_PATTERN.findall(sanitized_content)
        )
        return summary

    def _deduplicate_test_names(self, test_names: List[str]) -> List[str]:
        normalized_names = [
            str(test_name).strip() for test_name in test_names if test_name
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
