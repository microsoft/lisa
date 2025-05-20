# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import tempfile
import unittest
from pathlib import Path

from assertpy import assert_that

from lisa.main import initialize_runtime_folder, constants


class TestWorkingPath(unittest.TestCase):
    def test_working_path_honored(self) -> None:
        # Create a temporary directory to use as working path
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            # Initialize runtime folder with our temporary directory
            initialize_runtime_folder(working_path=temp_path)
            
            # Check that CACHE_PATH is within our temporary directory
            assert_that(str(constants.CACHE_PATH)).contains(temp_dir)
            
            # Check that RUN_LOCAL_WORKING_PATH is within our temporary directory
            assert_that(str(constants.RUN_LOCAL_WORKING_PATH)).contains(temp_dir)


if __name__ == "__main__":
    unittest.main()