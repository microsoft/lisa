# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import logging
import time
from pathlib import Path, PurePath
from typing import Any, Dict, List, Type

from assertpy.assertpy import assert_that

from lisa import Environment
from lisa.executable import Tool
from lisa.features import SerialConsole
from lisa.operating_system import CBLMariner, Ubuntu
from lisa.testsuite import TestResult
from lisa.tools import Cargo, Dmesg, Echo, Git, Make, Mkdir
from lisa.util import SkippedException, UnsupportedDistroException
from lisa.util.process import ExecutableResult

_log = logging.getLogger(__name__)

# Known error indicators that signal infrastructure unavailability
# (e.g., IMDS /acc/tdquote endpoint not exposed on the host)
_INFRA_ERROR_INDICATORS = ["InvalidUri", "TDQuoteException"]

_ATTESTATION_MAX_RETRIES = 3
_ATTESTATION_RETRY_DELAY_SECS = 30


class AzureCVMAttestationTests(Tool):
    repo = "https://github.com/Azure/cvm-attestation-tools.git"
    cmd_path: PurePath
    repo_root: PurePath

    @property
    def command(self) -> str:
        return str(self.cmd_path)

    @property
    def can_install(self) -> bool:
        return True

    def run_cvm_attestation(
        self,
        test_result: TestResult,
        environment: Environment,
        config: str,
        log_path: Path,
    ) -> None:
        config_path = self.attestation_dir / config

        # --- Platform Attestation (with retry) ---
        self._run_attestation_phase(
            phase="PLATFORM",
            command_option=f"--c {config_path}",
            success_message="Attested Platform Successfully",
            config=config,
            log_path=log_path,
        )

        # --- Guest Attestation (with retry) ---
        self._run_attestation_phase(
            phase="GUEST",
            command_option=f"--c {config_path} --t GUEST",
            success_message="Attested Guest Successfully",
            config=config,
            log_path=log_path,
        )

    def _run_attestation_phase(
        self,
        phase: str,
        command_option: str,
        success_message: str,
        config: str,
        log_path: Path,
    ) -> None:
        """Run a single attestation phase with retry logic.

        Retries up to _ATTESTATION_MAX_RETRIES times when known
        infrastructure error indicators are detected (e.g., IMDS endpoint
        not yet available).  If all retries are exhausted and the failure
        is due to infrastructure unavailability, raises SkippedException
        so the test is reported as SKIPPED rather than a false FAIL.
        """
        last_result: ExecutableResult = None  # type: ignore[assignment]
        last_output = ""
        last_stderr = ""
        found_infra_errors: List[str] = []

        for attempt in range(1, _ATTESTATION_MAX_RETRIES + 1):
            last_result = self.run(
                command_option,
                cwd=self.attestation_dir,
                shell=True,
                sudo=True,
                force_run=True,
            )

            last_output = last_result.stdout
            last_stderr = last_result.stderr
            self._save_attestation_report(last_output, log_path=log_path)

            _log.info(
                "%s attestation attempt %d/%d: command='attest %s', "
                "exit_code=%d",
                phase,
                attempt,
                _ATTESTATION_MAX_RETRIES,
                command_option,
                last_result.exit_code,
            )
            _log.info(
                "%s attestation stdout (last 2000 chars): %s",
                phase,
                last_output[-2000:] if len(last_output) > 2000 else last_output,
            )
            if last_stderr:
                _log.info(
                    "%s attestation stderr (last 1000 chars): %s",
                    phase,
                    last_stderr[-1000:] if len(last_stderr) > 1000 else last_stderr,
                )

            is_valid = (
                last_result.exit_code == 0 and success_message in last_output
            )
            if is_valid:
                _log.info(
                    "%s attestation PASSED on attempt %d.", phase, attempt
                )
                return

            # Check for infrastructure-level errors
            combined = last_output + last_stderr
            found_infra_errors = [
                ind for ind in _INFRA_ERROR_INDICATORS if ind in combined
            ]

            if found_infra_errors and attempt < _ATTESTATION_MAX_RETRIES:
                _log.warning(
                    "%s attestation failed with infra errors %s, "
                    "retrying in %ds (attempt %d/%d)...",
                    phase,
                    found_infra_errors,
                    _ATTESTATION_RETRY_DELAY_SECS,
                    attempt,
                    _ATTESTATION_MAX_RETRIES,
                )
                time.sleep(_ATTESTATION_RETRY_DELAY_SECS)
                continue

            # Non-infra failure or last attempt — break out
            break

        # All retries exhausted or non-retryable failure
        _log.error(
            "%s attestation FAILED after %d attempt(s). "
            "exit_code=%d, success_message_found=%s, config=%s",
            phase,
            _ATTESTATION_MAX_RETRIES,
            last_result.exit_code,
            success_message in last_output,
            config,
        )

        if found_infra_errors:
            raise SkippedException(
                f"CVM {phase.lower()} attestation infrastructure not available "
                f"after {_ATTESTATION_MAX_RETRIES} retries. "
                f"Detected infra errors: {found_infra_errors} in output. "
                f"The IMDS /acc/tdquote endpoint may not be exposed on this host."
            )

        assert_that(
            False,
            f"The CVM {phase.lower()}
            False,
            f"The CVM {phase.lower()} attestation test failed",
        ).is_true()

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        if not isinstance(self.node.os, Ubuntu):
            raise UnsupportedDistroException(
                self.node.os, "CVM attestation report tool supports only Ubuntu."
            )

        tool_path = self.get_tool_path(
            use_global=True,
        )

        repo_name = Path(self.repo).name.removesuffix(".git")

        self.repo_root = tool_path / repo_name
        self.attestation_dir = self.repo_root / "cvm-attestation"
        self.cmd_path = self.node.get_pure_path("/usr/local/bin") / "attest"

    def _clone_repo(self) -> None:
        git = self.node.tools[Git]
        root_path = self.get_tool_path(
            use_global=True,
        )
        git.clone(self.repo, root_path)

    def _install(self) -> bool:
        self._clone_repo()
        self.node.execute(
            "sudo ./install.sh",
            shell=True,
            cwd=self.attestation_dir,
        )
        return self._check_exists()

    def _save_attestation_report(self, output: str, log_path: Path) -> None:
        report_path = log_path / "cvm_test_report_combined.txt"
        with open(str(report_path), "a+") as f:
            f.write(output)


class SnpGuest(Tool):
    _snpguest_repo = "https://github.com/virtee/snpguest"
    cmd_path: PurePath
    repo_root: PurePath
    branch = "v0.8.3"

    @property
    def command(self) -> str:
        return str(self.cmd_path)

    @property
    def can_install(self) -> bool:
        return True

    @property
    def dependencies(self) -> List[Type[Tool]]:
        return [Git, Cargo, Mkdir]

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        tool_path = self.get_tool_path(use_global=True)

        self.repo_root = tool_path / "snpguest"
        self.cmd_path = self.repo_root / "target" / "release" / "snpguest"

    def _install(self) -> bool:
        if isinstance(self.node.os, CBLMariner):
            self.node.os.install_packages(["perl", "tpm2-tss-devel"])
        tool_path = self.get_tool_path(use_global=True)
        git = self.node.tools[Git]
        git.clone(self._snpguest_repo, tool_path, ref=self.branch)

        cargo = self.node.tools[Cargo]
        cargo.build(release=True, features="hyperv", sudo=False, cwd=self.repo_root)

        return self._check_exists()

    def _fetch_ca(
        self,
        certs_dir: str,
        encoding: str = "der",
        processor_model: str = "milan",
        endorser: str = "vcek",
    ) -> ExecutableResult:
        failure_msg = "failed to request CA chain from the KDS"
        return self.run(
            f"fetch ca {encoding} {processor_model} {certs_dir} --endorser {endorser}",
            expected_exit_code=0,
            expected_exit_code_failure_message=failure_msg,
            shell=True,
            sudo=False,
            force_run=True,
        )

    def _fetch_vcek(
        self,
        certs_dir: str,
        attestation_report_path: str,
        encoding: str = "der",
        processor_model: str = "milan",
    ) -> ExecutableResult:
        failure_msg = "failed to request VCEK from the KDS"
        return self.run(
            f"fetch vcek {encoding} {processor_model} {certs_dir} "
            f"{attestation_report_path}",
            expected_exit_code=0,
            expected_exit_code_failure_message=failure_msg,
            shell=True,
            sudo=False,
            force_run=True,
        )

    def _request_attestation_report(
        self, attestation_report_path: str, request_file_path: str
    ) -> ExecutableResult:
        failure_msg = "failed to request attestation report from the host"
        return self.run(
            f"report {attestation_report_path} {request_file_path} --platform --vmpl 0",
            expected_exit_code=0,
            expected_exit_code_failure_message=failure_msg,
            shell=True,
            sudo=True,
            force_run=True,
        )

    def _verify_certs(self, certs_dir: str) -> ExecutableResult:
        failure_msg = "failed to verify certificates"
        return self.run(
            f"verify certs {certs_dir}",
            expected_exit_code=0,
            expected_exit_code_failure_message=failure_msg,
            shell=True,
            sudo=False,
            force_run=True,
        )

    def _verify_attestation(
        self, certs_dir: str, attestation_report_path: str
    ) -> ExecutableResult:
        failure_msg = "failed to verify attestation report"
        return self.run(
            f"verify attestation {certs_dir} {attestation_report_path}",
            expected_exit_code=0,
            expected_exit_code_failure_message=failure_msg,
            shell=True,
            sudo=False,
            force_run=True,
        )

    def run_cvm_attestation(self, processor_model: str = "milan") -> None:
        """Regular attestation workflow

        1. Request attestation report
        2. Request AMD Root Key (ARK) and AMD SEV Key (ASK) from AMD Key Distribution
           Service (KDS)
        3. Request the Versioned Chip Endorsement Key (VCEK) from AMD KDS
        4. Verify the certificates obtained
        5. Verify the attestation report
        """
        data_dir = self.repo_root / "data"
        certs_dir = data_dir / "certs"
        attestation_report_path = data_dir / "attestation-report.bin"
        request_file_path = data_dir / "request-file.txt"

        mkdir = self.node.tools[Mkdir]
        mkdir.create_directory(certs_dir.as_posix())

        self._request_attestation_report(
            attestation_report_path.as_posix(), request_file_path.as_posix()
        )
        self._fetch_ca(certs_dir.as_posix(), processor_model=processor_model)
        self._fetch_vcek(
            certs_dir.as_posix(),
            attestation_report_path.as_posix(),
            processor_model=processor_model,
        )

        self._verify_certs(certs_dir.as_posix())
        self._verify_attestation(
            certs_dir.as_posix(), attestation_report_path.as_posix()
        )


class NestedCVMAttestationTests(Tool):
    repo = "https://github.com/microsoft/confidential-sidecar-containers.git"
    cmd_path: str
    repo_root: PurePath

    @property
    def command(self) -> str:
        return str(self.cmd_path)

    @property
    def can_install(self) -> bool:
        return True

    @property
    def dependencies(self) -> List[Type[Tool]]:
        return [Make]

    def run_cvm_attestation(
        self,
        test_result: TestResult,
        environment: Environment,
        log_path: Path,
        host_data: str,
    ) -> None:
        failure_msg = "CVM attestation report generation failed"
        command = self.run(
            f" | {self.hex_2_report_cmd}",
            expected_exit_code=0,
            expected_exit_code_failure_message=failure_msg,
            shell=True,
            sudo=True,
        )

        output: str = command.stdout
        result = self._extract_result(output)
        self._log.debug(f"Attestation result: {result}")
        attestation_host_data = result["host_data"].replace(" ", "").strip()

        assert_that(
            host_data,
            "'host_data' passed to testcase is not matching with attestation result",
        ).is_equal_to(attestation_host_data)

        # save the attestation report under log_path as cvm_attestation_report.txt
        self._save_attestation_report(output, log_path)

        # save the guest kernel log
        self._save_kernel_logs(log_path=log_path)

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        echo = self.node.tools[Echo]

        tool_path = PurePath(
            echo.run(
                "$HOME",
                shell=True,
                expected_exit_code=0,
                expected_exit_code_failure_message="failed to get $HOME via echo",
            ).stdout
        )

        self.repo_root = tool_path / "confidential-sidecar-containers"
        self.snp_report_tool_path = self.repo_root / "tools" / "get-snp-report"
        self.get_snp_report_cmd = self.snp_report_tool_path / "bin" / "get-snp-report"
        self.hex_2_report_cmd = self.snp_report_tool_path / "bin" / "hex2report"
        self.cmd_path = f"{self.get_snp_report_cmd}"

    def _install(self) -> bool:
        echo = self.node.tools[Echo]
        git = self.node.tools[Git]

        root_path = PurePath(
            echo.run(
                "$HOME",
                shell=True,
                expected_exit_code=0,
                expected_exit_code_failure_message="failed to get $HOME via echo",
            ).stdout
        )

        git.clone(self.repo, Path(root_path))
        make = self.node.tools[Make]
        make.make("", cwd=self.snp_report_tool_path)

        return self._check_exists()

    def _extract_result(self, output: str) -> Dict[str, str]:
        records: List[str] = output.split("\n")
        records = [line for line in records if line != ""]
        result: Dict[str, str] = {}
        for line in records:
            if line.find(":") >= 0:
                data = line.split(":")
                variable = data[0].strip()
                result[variable] = data[1]
            else:
                result[variable] = f"{result[variable]}\n{line}"
        return result

    def _save_kernel_logs(self, log_path: Path) -> None:
        # Use serial console if available. Serial console logs can be obtained
        # even if the node goes down (hung, panicked etc.). Whereas, dmesg
        # can only be used if node is up and LISA is able to connect via SSH.
        if self.node.features.is_supported(SerialConsole):
            serial_console = self.node.features[SerialConsole]
            serial_console.get_console_log(log_path, force_run=True)
        else:
            dmesg_str = self.node.tools[Dmesg].get_output(force_run=True)
            dmesg_path = log_path / "dmesg"
            with open(str(dmesg_path), "w") as f:
                f.write(dmesg_str)

    def _save_attestation_report(self, output: str, log_path: Path) -> None:
        report_path = log_path / "cvm_attestation_report.txt"
        with open(str(report_path), "w") as f:
            f.write(output)
