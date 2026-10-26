# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from unittest import TestCase
from unittest.mock import MagicMock, patch

from lisa.tools import Fio

_FIO_OUTPUT = (
    "iteration0_0: (groupid=0, jobs=6): err= 0: pid=1234\n"
    "  write: IOPS=191k, BW=749MiB/s (785MB/s)(87.8GiB/120002msec)\n"
    "    slat (usec): min=1, max=9000, avg=1270.11, stdev=10.00\n"
    "    clat (usec): min=800, max=600000, avg=84150.20, stdev=100.00\n"
    "     lat (usec): min=850, max=600100, avg=85420.31, stdev=100.00\n"
)


class FioToolTestCase(TestCase):
    def _create_fio(self) -> Fio:
        fio = Fio.__new__(Fio)
        fio.node = MagicMock()
        return fio

    def test_per_file_jobs_create_one_job_per_file(self) -> None:
        fio = self._create_fio()

        cmd = fio._get_command(
            "iteration0",
            "/dev/sdc1:/dev/sdd1:/dev/sde1",
            "randwrite",
            64,
            numjob=2,
            size_gb=8192,
            overwrite=True,
            per_file_jobs=True,
            offset_increment_mb=8192,
        )

        first_job = cmd.index("--name=")
        global_options = cmd[:first_job]
        for option in (
            "--readwrite=randwrite",
            "--iodepth=64",
            "--numjob=2",
            "--size=8192M",
            "--offset_increment=8192M",
            "--overwrite=1",
            "--group_reporting",
        ):
            self.assertIn(option, global_options)
        self.assertNotIn("--filename=", global_options)
        self.assertTrue(
            cmd[first_job:].endswith(
                "--name=iteration0_0 --filename=/dev/sdc1 "
                "--name=iteration0_1 --filename=/dev/sdd1 "
                "--name=iteration0_2 --filename=/dev/sde1"
            )
        )

    def test_default_command_keeps_shared_filename(self) -> None:
        fio = self._create_fio()

        cmd = fio._get_command("iteration0", "/dev/sdc1:/dev/sdd1", "randread", 4)

        self.assertIn("--filename=/dev/sdc1:/dev/sdd1", cmd)
        self.assertEqual(1, cmd.count("--name="))
        self.assertNotIn("--offset_increment", cmd)

    def test_per_file_launch_reports_total_outstanding_io(self) -> None:
        fio = self._create_fio()
        run_result = MagicMock(exit_code=0, stdout=_FIO_OUTPUT)

        with patch.object(fio, "run", return_value=run_result):
            result = fio.launch(
                name="iteration0",
                filename="/dev/sdc1:/dev/sdd1:/dev/sde1",
                mode="randwrite",
                iodepth=64,
                numjob=2,
                per_file_jobs=True,
            )

        self.assertEqual(64 * 2 * 3, result.qdepth)
        self.assertEqual(191000, result.iops)
