#!/usr/bin/env python
# This script tests that the working_path parameter is correctly honored

import os
import sys
import tempfile
from pathlib import Path

if __name__ == "__main__":
    # Create a temporary directory to use as working_path
    with tempfile.TemporaryDirectory() as temp_dir:
        print(f"Testing with temporary directory: {temp_dir}")
        
        # Import initialize_runtime_folder after creating temp dir to avoid early import
        from lisa.main import initialize_runtime_folder
        
        # Initialize runtime with the temp_dir as working_path
        initialize_runtime_folder(working_path=Path(temp_dir))
        
        # Import constants after initialization
        from lisa.util import constants
        
        # Check if CACHE_PATH is under the provided working_path
        cache_path = constants.CACHE_PATH
        expected_path = Path(temp_dir) / "runtime" / "cache"
        
        print(f"Expected cache path: {expected_path}")
        print(f"Actual cache path: {cache_path}")
        
        if cache_path == expected_path:
            print("SUCCESS: Cache path is correctly set under the provided working_path")
            sys.exit(0)
        else:
            print("FAILURE: Cache path is not under the provided working_path")
            sys.exit(1)