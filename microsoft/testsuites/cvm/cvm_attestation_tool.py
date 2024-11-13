# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import json
from pathlib import Path, PurePath
from typing import Any, Dict, List, Type, cast

import jwt
from assertpy.assertpy import assert_that

from lisa import Environment
from lisa.executable import Tool
from lisa.features import SerialConsole
from lisa.operating_system import Posix, Ubuntu
from lisa.testsuite import TestResult
from lisa.tools import Dmesg, Echo, Git, Make
from lisa.util import UnsupportedDistroException


class AzureCVMAttestationTests(Tool):
    repo = "https://github.com/Azure/confidential-computing-cvm-guest-attestation"
    cmd_path: PurePath
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
    ) -> None:
        failure_msg = "CVM attestation report generation failed"

        command = self.run(
            "-o token",
            expected_exit_code=0,
            expected_exit_code_failure_message=failure_msg,
            cwd=self.snp_report_tool_path,
            shell=True,
            sudo=True,
            force_run=True,
        )

        output: str = command.stdout
        report = jwt.decode(
            output, algorithms=["RS256"], options={"verify_signature": False}
        )

        self._save_attestation_report(json.dumps(report), log_path=log_path)

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        if not isinstance(self.node.os, Ubuntu):
            raise UnsupportedDistroException(
                self.node.os, "CVM attestation report tool supports only Ubuntu."
            )

        tool_path = self.get_tool_path(
            use_global=True,
        )

        self.repo_root = tool_path / "confidential-computing-cvm-guest-attestation"
        self.snp_report_tool_path = self.repo_root / "cvm-attestation-sample-app"
        self.deb_file = (
            "https://packages.microsoft.com/repos/"
            "azurecore/pool/main/a/azguestattestation1/"
            "azguestattestation1_1.0.5_amd64.deb"
        )
        self.cmd_path = self.snp_report_tool_path / "AttestationClient"

    def _install(self) -> bool:
        self._install_dep_packages()
        git = self.node.tools[Git]
        posix_os: Posix = cast(Posix, self.node.os)

        root_path = self.get_tool_path(
            use_global=True,
        )

        git.clone(self.repo, root_path)

        posix_os._install_package_from_url(
            self.deb_file, package_name="azguestattestation1.deb"
        )
        self.node.execute(
            "cmake .",
            shell=True,
            cwd=self.snp_report_tool_path,
        )
        make = self.node.tools[Make]
        make.make("", cwd=self.snp_report_tool_path)

        return self._check_exists()

    def _install_dep_packages(self) -> None:
        # Installing packages supported by Ubuntu
        posix_os: Posix = cast(Posix, self.node.os)
        package_list = [
            "build-essential",
            "libcurl4-openssl-dev",
            "libjsoncpp-dev",
            "wget",
            "libboost-all-dev",
            "nlohmann-json3-dev",
            "cmake",
        ]
        posix_os.install_packages(package_list)

    def _save_attestation_report(self, output: str, log_path: Path) -> None:
        report_path = log_path / "cvm_attestation_report.txt"
        with open(str(report_path), "w") as f:
            f.write(output)


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

        assert_that(
            host_data,
            "'host_data' passed to testcase is not matching with attestation result",
        ).is_equal_to(result["host_data"].strip())

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
