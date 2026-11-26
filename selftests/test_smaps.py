# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Dict
from unittest import TestCase
from unittest.mock import MagicMock, patch

from lisa.tools.smaps import Smaps
from lisa.util import LisaException
from lisa.util.process import ExecutableResult


class SmapsTestCase(TestCase):
    def _get_page_sizes(self, stdout: str) -> Dict[str, int]:
        smaps = Smaps.__new__(Smaps)
        smaps.node = MagicMock()
        smaps.node.get_pure_path.return_value = "/proc/self/smaps"
        result = ExecutableResult(stdout, "", 0, "cat /proc/self/smaps", "smaps", 0)
        with patch.object(smaps, "run", return_value=result) as run:
            page_sizes = smaps.get_page_sizes()
        run.assert_called_once_with(
            "/proc/self/smaps",
            force_run=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "Failed to read /proc/self/smaps. Check procfs availability and "
                "CONFIG_PROC_PAGE_MONITOR on the guest."
            ),
        )
        return page_sizes

    def test_page_sizes_with_lf_and_crlf(self) -> None:
        for newline in ("\n", "\r\n"):
            for size_kb in (4, 64):
                with self.subTest(newline=repr(newline), size_kb=size_kb):
                    stdout = newline.join(
                        [
                            "b0d1b9a50000-b0d1b9a57000 r-xp 00000000 103:01 "
                            "1739 /bin/cat",
                            "Size:                 28 kB",
                            f"KernelPageSize:        {size_kb} kB",
                            f"MMUPageSize:           {size_kb} kB",
                            "Rss:                  28 kB",
                        ]
                    )
                    self.assertEqual(
                        self._get_page_sizes(stdout),
                        {
                            "KernelPageSize": size_kb * 1024,
                            "MMUPageSize": size_kb * 1024,
                        },
                    )

    def test_only_first_mapping_is_used(self) -> None:
        for newline in ("\n", "\r\n"):
            with self.subTest(newline=repr(newline)):
                stdout = newline.join(
                    [
                        "1000-2000 r-xp 00000000 00:00 0",
                        "KernelPageSize:\t4 kB \t",
                        "MMUPageSize:\t64 kB\t",
                        "2000-3000 rw-p 00000000 00:00 0",
                        "KernelPageSize: 64 kB",
                        "MMUPageSize: 4 kB",
                    ]
                )
                self.assertEqual(
                    self._get_page_sizes(stdout),
                    {"KernelPageSize": 4096, "MMUPageSize": 65536},
                )

    def test_missing_mapping_raises(self) -> None:
        for stdout in ("", "KernelPageSize: 4 kB\nMMUPageSize: 4 kB"):
            with self.subTest(stdout=stdout):
                with self.assertRaisesRegex(LisaException, "No process mapping found"):
                    self._get_page_sizes(stdout)

    def test_missing_field_in_first_mapping_raises(self) -> None:
        for newline in ("\n", "\r\n"):
            for field in ("KernelPageSize", "MMUPageSize"):
                with self.subTest(newline=repr(newline), field=field):
                    other = (
                        "MMUPageSize" if field == "KernelPageSize" else "KernelPageSize"
                    )
                    stdout = newline.join(
                        [
                            "1000-2000 r-xp 00000000 00:00 0",
                            f"{other}: 4 kB",
                            "2000-3000 rw-p 00000000 00:00 0",
                            f"{field}: 4 kB",
                        ]
                    )
                    with self.assertRaisesRegex(
                        LisaException, f"Missing or malformed {field}"
                    ):
                        self._get_page_sizes(stdout)

    def test_malformed_field_raises(self) -> None:
        for newline in ("\n", "\r\n"):
            for field in ("KernelPageSize", "MMUPageSize"):
                for value in ("four kB", "4 MB", "-4 kB", "4 kB unexpected"):
                    with self.subTest(newline=repr(newline), field=field, value=value):
                        fields = {"KernelPageSize": "4 kB", "MMUPageSize": "4 kB"}
                        fields[field] = value
                        stdout = newline.join(
                            ["1000-2000 r-xp 00000000 00:00 0"]
                            + [f"{name}: {text}" for name, text in fields.items()]
                        )
                        with self.assertRaisesRegex(
                            LisaException, f"Missing or malformed {field}"
                        ):
                            self._get_page_sizes(stdout)

    def test_read_failure_propagates(self) -> None:
        smaps = Smaps.__new__(Smaps)
        smaps.node = MagicMock()
        error = LisaException("Failed to read /proc/self/smaps")
        with patch.object(smaps, "run", side_effect=error):
            with self.assertRaises(LisaException) as raised:
                smaps.get_page_sizes()
        self.assertIs(raised.exception, error)
