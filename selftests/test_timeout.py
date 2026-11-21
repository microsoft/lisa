# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import shutil
import subprocess
import sys
from unittest import TestCase, skipUnless
from unittest.mock import Mock, patch

from lisa.tools.timeout import Timeout
from lisa.util.constants import SIGINT, SIGTERM


class TimeoutTestCase(TestCase):
    def test_foreground_is_opt_in(self) -> None:
        tool = Timeout.__new__(Timeout)
        for foreground in (False, True):
            with self.subTest(foreground=foreground):
                with patch.object(tool, "run_async") as run:
                    tool.start_with_timeout(
                        "testpmd", 30, SIGINT, kill_timeout=40, foreground=foreground
                    )
                    prefix = "--foreground " if foreground else ""
                    run.assert_called_once_with(
                        parameters=(
                            f"{prefix}--kill-after 40 -s {SIGINT} "
                            "--preserve-status 30 testpmd"
                        ),
                        force_run=True,
                        shell=True,
                        sudo=True,
                    )

    def test_run_forwards_foreground_option(self) -> None:
        tool = Timeout.__new__(Timeout)
        process = Mock()
        with patch.object(tool, "start_with_timeout", return_value=process) as start:
            result = tool.run_with_timeout("testpmd", 30, foreground=True)
            start.assert_called_once_with(
                command="testpmd",
                timeout=30,
                signal=SIGTERM,
                kill_timeout=0,
                foreground=True,
            )
            process.wait_result.assert_called_once_with(timeout=40)
            self.assertIs(result, process.wait_result.return_value)

    @skipUnless(
        sys.platform == "linux" and shutil.which("timeout"),
        "Requires GNU timeout on Linux",
    )
    def test_foreground_allows_sigint_cleanup(self) -> None:
        script = (
            "import signal, time\n"
            "def stop(signum, frame):\n"
            "    signal.signal(signal.SIGINT, signal.SIG_DFL)\n"
            "    time.sleep(0.2)\n"
            "    print('shutdown statistics', flush=True)\n"
            "    raise SystemExit(0)\n"
            "signal.signal(signal.SIGINT, stop)\n"
            "while True:\n"
            "    time.sleep(0.1)\n"
        )
        result = subprocess.run(
            [
                "timeout",
                "--foreground",
                "--preserve-status",
                "--kill-after=2",
                "-s",
                str(SIGINT),
                "1",
                sys.executable,
                "-c",
                script,
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "shutdown statistics")
