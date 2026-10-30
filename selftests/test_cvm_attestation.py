# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import MagicMock, call, patch

from lisa.microsoft.testsuites.cvm.cvm_attestation_tool import AzureCVMAttestationTests
from lisa.util.process import ExecutableResult


class AzureCVMAttestationTestCase(TestCase):
    def setUp(self) -> None:
        self.tool = AzureCVMAttestationTests.__new__(AzureCVMAttestationTests)
        self.tool.attestation_dir = PurePosixPath("/attestation")
        self.platform_output = "Attested Platform Successfully\n"
        self.guest_output = "Attested Guest Successfully\n"

    def test_platform_and_guest_use_matching_configurations(self) -> None:
        for isolation in ("snp", "tdx"):
            with self.subTest(isolation=isolation), TemporaryDirectory() as directory:
                log_path = Path(directory)
                with patch.object(
                    self.tool,
                    "run",
                    side_effect=[
                        MagicMock(
                            spec=ExecutableResult,
                            stdout=self.platform_output,
                            exit_code=0,
                        ),
                        MagicMock(
                            spec=ExecutableResult, stdout=self.guest_output, exit_code=0
                        ),
                    ],
                ) as run:
                    self.tool.run_cvm_attestation(
                        MagicMock(),
                        MagicMock(),
                        f"config_{isolation}.json",
                        f"config_{isolation}_guest.json",
                        log_path,
                    )

                self.assertEqual(
                    [
                        call(
                            f"--c /attestation/config_{isolation}.json --t PLATFORM",
                            cwd=self.tool.attestation_dir,
                            shell=True,
                            sudo=True,
                            force_run=True,
                        ),
                        call(
                            f"--c /attestation/config_{isolation}_guest.json --t GUEST",
                            cwd=self.tool.attestation_dir,
                            shell=True,
                            sudo=True,
                            force_run=True,
                        ),
                    ],
                    run.call_args_list,
                )
                self.assertEqual(
                    self.platform_output + self.guest_output,
                    (log_path / "cvm_test_report_combined.txt").read_text(),
                )

    def test_platform_failure_stops_before_guest_attestation(self) -> None:
        for output, exit_code in (
            ("ClientInfo is empty\n", 0),
            (self.platform_output, 1),
        ):
            with self.subTest(exit_code=exit_code), TemporaryDirectory() as directory:
                log_path = Path(directory)
                with patch.object(
                    self.tool,
                    "run",
                    return_value=MagicMock(
                        spec=ExecutableResult, stdout=output, exit_code=exit_code
                    ),
                ) as run:
                    with self.assertRaisesRegex(
                        AssertionError, "The CVM platform attestation test failed"
                    ):
                        self.tool.run_cvm_attestation(
                            MagicMock(),
                            MagicMock(),
                            "config_tdx.json",
                            "config_tdx_guest.json",
                            log_path,
                        )

                run.assert_called_once()
                self.assertEqual(
                    output, (log_path / "cvm_test_report_combined.txt").read_text()
                )

    def test_guest_failure_is_reported_and_saved(self) -> None:
        for output, exit_code in (
            ("Token was not received from attestation provider\n", 0),
            (self.guest_output, 1),
        ):
            with self.subTest(exit_code=exit_code), TemporaryDirectory() as directory:
                log_path = Path(directory)
                with patch.object(
                    self.tool,
                    "run",
                    side_effect=[
                        MagicMock(
                            spec=ExecutableResult,
                            stdout=self.platform_output,
                            exit_code=0,
                        ),
                        MagicMock(
                            spec=ExecutableResult, stdout=output, exit_code=exit_code
                        ),
                    ],
                ) as run:
                    with self.assertRaisesRegex(
                        AssertionError, "The CVM guest attestation test failed"
                    ):
                        self.tool.run_cvm_attestation(
                            MagicMock(),
                            MagicMock(),
                            "config_tdx.json",
                            "config_tdx_guest.json",
                            log_path,
                        )

                self.assertEqual(2, run.call_count)
                self.assertEqual(
                    self.platform_output + output,
                    (log_path / "cvm_test_report_combined.txt").read_text(),
                )
