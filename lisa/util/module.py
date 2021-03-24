# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import importlib
import importlib.util
import sys
from pathlib import Path
from typing import Optional

from lisa.util.logger import get_logger


def import_package(
    path: Path, index: Optional[int] = None, enable_log: bool = True
) -> None:

    if not path.exists():
        raise FileNotFoundError(f"import module path: {path}")

    log = get_logger("init", "module")

    package_name = path.stem
    global packages
    packages.append(package_name)
    package_dir = path.parent
    sys.path.append(str(package_dir))
    if enable_log:
        log.info(f"loading extension from {path}")

    for file in path.glob("**/*.py"):
        file_name = file.stem
        if file_name.startswith("__"):
            continue
        # skip test files
        if "tests" == file.parent.stem and file_name.startswith("test_"):
            continue

        dir_name = file.parent
        local_package_path = dir_name.relative_to(package_dir)
        local_package_name = ".".join(local_package_path.parts)
        if index is not None:
            local_package_name = f"lisa_ext_{index}.{local_package_name}"

        full_module_name = f"{local_package_name}.{file_name}"

        if full_module_name not in sys.modules:
            if enable_log:
                log.debug(f"  loading module from file: {file}")
                log.debug(
                    f"  package: '{local_package_name}', "
                    f"full_module_name: '{full_module_name}' "
                )

            spec = importlib.util.spec_from_file_location(full_module_name, file)
            module = importlib.util.module_from_spec(spec)
            assert spec
            assert spec.loader
            sys.modules[full_module_name] = module
            spec.loader.exec_module(module)  # type: ignore


packages = ["lisa"]
