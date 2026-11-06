# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from lisa.notifiers.junit import JUnit, JUnitSchema
from lisa.util import constants


class JUnitInitializationTestCase(TestCase):
    def test_failed_initial_write_preserves_existing_report(self) -> None:
        with TemporaryDirectory() as temp_dir:
            report_path = Path(temp_dir) / "report.xml"
            original_report = b"existing report"
            report_path.write_bytes(original_report)

            notifier = JUnit(JUnitSchema(type="junit", path=report_path.name))
            original_open = Path.open

            def open_temporary_file(path: Path, mode: str = "r") -> object:
                if path.name == ".report.xml.tmp":
                    raise PermissionError("directory is not writable")
                return original_open(path, mode)

            with patch.object(constants, "RUN_LOCAL_LOG_PATH", Path(temp_dir)):
                with patch.object(Path, "open", autospec=True) as mock_open:
                    mock_open.side_effect = open_temporary_file
                    with self.assertRaises(PermissionError):
                        notifier._initialize()

            self.assertEqual(report_path.read_bytes(), original_report)
