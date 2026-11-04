# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import hashlib
import json
import re
import shlex
import sys
import uuid
import xml.etree.ElementTree as ETree
from dataclasses import dataclass, field
from pathlib import Path, PurePath
from typing import Any, Dict, List, Optional, Tuple, Type, cast

from lisa.executable import Tool
from lisa.operating_system import CBLMariner, Posix
from lisa.tools import Cargo, Curl, Docker, Git, Ls, Uname
from lisa.util import LisaException, SkippedException, UnsupportedDistroException


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
    CONTAINER_ARTIFACT_ROOT = "/lisa-openvmm"
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
    _container_name = ""
    _image_name = ""

    _distro_package_mapping = {
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
        # Native execution resolves Cargo lazily; container runs need no host Rust.
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
        ref: str = "",
        release: bool = False,
        test_filter: str = "",
        install_missing_deps: bool = True,
        skip_vhd_prompt: bool = True,
        ci_profile: bool = False,
    ) -> _JUnitSummary:
        try:
            env = self._prepare_repo(log_path, ref, ci_profile=ci_profile)
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
                "cargo" if ci_profile else self.node.tools[Cargo].command,
                "xflowey",
                "vmm-tests-run",
                "--target",
                "linux-x64",
                "--dir",
                (
                    f"{self.CONTAINER_ARTIFACT_ROOT}/vmm-tests-run"
                    if ci_profile
                    else str(output_dir)
                ),
            ]
            if install_missing_deps:
                command.append("--install-missing-deps")
            if skip_vhd_prompt:
                command.append("--skip-vhd-prompt")
            if release:
                command.append("--release")
            if ci_profile:
                command.extend(["--ci-profile", "--no-reuse-prepped-vhds"])
            if test_filter:
                command.extend(["--filter", test_filter])

            wrapped_command = shlex.join(command)
            if not ci_profile:
                wrapped_command = self._wrap_command_for_group(wrapped_command)
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
        finally:
            container_name = self._container_name
            image_name = self._image_name
            self._container_name = ""
            self._image_name = ""
            if container_name:
                self._repo_prepared = False
            try:
                if container_name:
                    self.node.tools[Docker].run(
                        f"rm --force {shlex.quote(container_name)}",
                        sudo=True,
                        force_run=True,
                        expected_exit_code=0,
                        expected_exit_code_failure_message=(
                            "failed to remove the OpenVMM MSHV test container"
                        ),
                    )
            finally:
                if image_name:
                    result = self.node.tools[Docker].run(
                        f"rmi --force {shlex.quote(image_name)}",
                        sudo=True,
                        force_run=True,
                        expected_exit_code=None,
                    )
                    if result.exit_code != 0:
                        self._log.warning(
                            f"failed to remove the OpenVMM MSHV test image "
                            f"{image_name}: {result.stderr}"
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
        try:
            ref, ref_source = self._resolve_prebuilt_tests_ref(ref)
            env = self._prepare_repo(log_path, ref)
            # Petri creates Unix sockets beneath this path (limited to 108 bytes).
            output_dir = self.node.get_pure_path(
                self.node.execute(
                    "mktemp -d /tmp/ovmm-XXXXXXXX",
                    shell=True,
                    expected_exit_code=0,
                    expected_exit_code_failure_message=(
                        "failed to create a short OpenVMM test output directory"
                    ),
                ).stdout.strip()
            )
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
                if output_dir is not None:
                    # Preserve the original test error if cleanup also fails.
                    has_error = sys.exc_info()[0] is not None
                    try:
                        if not re.fullmatch(
                            r"/tmp/ovmm-[A-Za-z0-9]{8}", str(output_dir)
                        ):
                            raise LisaException(
                                f"Refusing to remove unexpected test path: {output_dir}"
                            )
                        self.node.execute(
                            f"rm -rf -- {shlex.quote(str(output_dir))}",
                            shell=True,
                            expected_exit_code=0,
                            expected_exit_code_failure_message=(
                                f"failed to remove OpenVMM test directory: {output_dir}"
                            ),
                        )
                    except (AssertionError, LisaException, OSError) as error:
                        self._log.error(
                            f"OpenVMM test directory cleanup failed: {error}"
                        )
                        if not has_error:
                            raise

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
        version = self.node.execute(
            f"{shlex.quote(identity[0])} --version",
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "failed to query prebuilt OpenVMM version"
            ),
        ).stdout.strip()
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

    def _prepare_repo(
        self, log_path: Path, ref: str, ci_profile: bool = False
    ) -> Dict[str, str]:
        git = self.node.tools[Git]
        if not self._check_exists() and not self._install():
            raise LisaException(
                f"failed to prepare OpenVMM upstream tests repository from "
                f"{self.repo_url}"
            )

        cargo_env = {} if ci_profile else self._get_cargo_environment()
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

        if ci_profile:
            self._prepare_ci_container(log_path)

        if not self._repo_prepared:
            restore_args = [
                "cargo" if ci_profile else self.node.tools[Cargo].command,
                "xflowey",
                "restore-packages",
                "--no-compat-igvm",
            ]
            if ci_profile:
                restore_args.append("x86-64")
            self._run_logged_command(
                name="openvmm_restore_packages",
                command=shlex.join(restore_args),
                log_path=log_path,
                timeout=self.RESTORE_TIMEOUT,
                update_envs=cargo_env,
            )
            self._repo_prepared = True
            self._prepared_ref = ref or ""

        self._ensure_cargo_nextest(log_path, cargo_env)

        return cargo_env

    def _prepare_ci_container(self, log_path: Path) -> None:
        docker = self.node.tools[Docker]
        identity = self.node.execute(
            "id -u && id -g", shell=True, expected_exit_code=0
        ).stdout.split()
        if len(identity) != 2 or not all(value.isdecimal() for value in identity):
            raise LisaException("failed to determine the MSHV checkout owner's UID/GID")
        host_uid, host_gid = identity
        build_dir = self._artifact_root / "container-build"
        self.node.execute(
            f"mkdir -p {shlex.quote(str(build_dir))}",
            shell=True,
            expected_exit_code=0,
        )
        self.node.shell.copy(
            Path(__file__).with_name("mshv.Dockerfile"), build_dir / "Dockerfile"
        )
        image_name = f"lisa-openvmm-mshv:{uuid.uuid4().hex}"
        self._image_name = image_name
        self._run_logged_command(
            name="openvmm_build_container",
            command=(
                f"{docker.command} build --pull "
                f"--build-arg HOST_UID={host_uid} --build-arg HOST_GID={host_gid} "
                f"--tag {image_name} {shlex.quote(str(build_dir))}"
            ),
            log_path=log_path,
            timeout=self.RESTORE_TIMEOUT,
            update_envs={},
            sudo=True,
        )
        container_name = f"lisa-openvmm-{uuid.uuid4().hex}"
        # io_uring and AF_VSOCK are needed by OpenVMM but blocked by Docker seccomp.
        docker.run(
            f"run --detach --rm --init --name {container_name} "
            "--device /dev/mshv --device /dev/vhost-vsock "
            '--group-add "$(stat -c %g /dev/mshv)" '
            '--group-add "$(stat -c %g /dev/vhost-vsock)" '
            "--sysctl net.ipv6.conf.all.disable_ipv6=0 "
            "--security-opt seccomp=unconfined "
            f"--volume {shlex.quote(f'{self.repo_root}:{self.repo_root}')} "
            "--volume "
            f"{shlex.quote(f'{self._artifact_root}:{self.CONTAINER_ARTIFACT_ROOT}')} "
            f"--workdir {shlex.quote(str(self.repo_root))} "
            f"{image_name} sleep infinity",
            shell=True,
            sudo=True,
            force_run=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="failed to start MSHV test container",
        )
        self._container_name = container_name
        self._repo_prepared = False
        self.node.execute(
            self._wrap_container_command(
                "test -r /dev/mshv && test -w /dev/mshv && "
                "test -r /dev/vhost-vsock && test -w /dev/vhost-vsock && "
                "cargo --version && rustc --version && "
                "targets=$(rustup target list --installed) && "
                "for target in x86_64-unknown-linux-musl x86_64-pc-windows-gnu; do "
                'printf \'%s\\n\' "$targets" | grep -Fxq "$target" || '
                '{ echo "Missing Rust target: $target" >&2; exit 1; }; done && '
                "rustup component list --installed | grep -q '^rust-src'"
            ),
            sudo=True,
            shell=True,
            timeout=self.RESTORE_TIMEOUT,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "MSHV container device access or installed Rust prerequisites failed"
            ),
        )

    def _wrap_container_command(self, command: str) -> str:
        if not self._container_name:
            return command
        return (
            f"{self.node.tools[Docker].command} exec "
            f"{shlex.quote(self._container_name)} bash -c {shlex.quote(command)}"
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
        command = self._wrap_container_command(command)
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
            sudo=sudo or bool(self._container_name),
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
        version = self._get_nextest_version()
        if self._has_cargo_nextest(update_envs, version):
            return

        self._log.debug(
            f"cargo-nextest {version} was not available after restore-packages; "
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
        curl_command = "curl" if self._container_name else self.node.tools[Curl].command
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
            self._wrap_container_command("cargo nextest --version"),
            shell=True,
            sudo=bool(self._container_name),
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
        summary.tests -= summary.skipped
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
