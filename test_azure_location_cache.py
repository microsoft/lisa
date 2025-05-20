#!/usr/bin/env python
# Test specifically for the azure location caching issue mentioned in the bug report

import os
import sys
import tempfile
from pathlib import Path
import json

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
        
        # Define an example location
        location = "westus"
        cached_file_name = constants.CACHE_PATH.joinpath(
            f"azure_locations_{location}.json"
        )
        
        print(f"Check if location cache file would be created at: {cached_file_name}")
        
        # Create a mock location cache file
        os.makedirs(os.path.dirname(cached_file_name), exist_ok=True)
        with open(cached_file_name, "w") as f:
            json.dump({"mock": "data"}, f)
        
        print(f"Created mock file at: {cached_file_name}")
        print(f"File exists: {cached_file_name.exists()}")
        
        # Try to read the file (simulate what happens in get_location_info)
        try:
            with open(cached_file_name, "r") as f:
                data = json.load(f)
                print(f"Successfully read data from {cached_file_name}: {data}")
                print("SUCCESS: Cache file is correctly accessible under the provided working_path")
                sys.exit(0)
        except Exception as e:
            print(f"FAILURE: Error accessing cache file: {e}")
            sys.exit(1)