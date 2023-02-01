# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""
Reasons to import packages in LISA:

1. Some modules are not  imported by Python automatically. So it needs to search and
   import from LISA path.
2. The extension folders need to be imported also. But the extension folders may have
   conflict names like testsuites. So it needs to rename.

Steps,

1. Import the root folder as a package. It's used by importlib.import_module
2. Go through all files, and check if it exists in sys.modules. If it's not, import it.

"""

import importlib
import importlib.util
import sys
from pathlib import Path
from typing import Iterable, Optional

from lisa.util.logger import Logger, get_logger


def _import_module(
    file: Path,
    root_package_name: Optional[str],
    package_dir: Path,
    log: Optional[Logger] = None,
) -> None:
    dir_name = file.parent
    module_name = file.stem
    relative_module_path = dir_name.relative_to(package_dir)
    relative_package_name = ".".join(relative_module_path.parts)
    module_name = f"{relative_package_name}.{module_name}"

    if root_package_name:
        if not module_name.startswith("."):
            # convert every module to relative package to replace the new namespace
            module_name = f".{module_name}"
        # use to check if the package imported already.
        # if it's imported, then skip.
        full_module_name = f"{root_package_name}{module_name}"
    else:
        full_module_name = module_name

    if full_module_name not in sys.modules:
        if log:
            log.debug(
                f"  loading module from file: {file}, "
                f"full_module_name: '{full_module_name}'",
            )

        importlib.import_module(name=module_name, package=root_package_name)


def _import_root_package(package_name: str, path: Path) -> None:
    # the module can be imported with __init__.py only, but it doesn't need to exist
    init_file = path / "__init__.py"
    spec = importlib.util.spec_from_file_location(
        name=package_name,
        location=init_file,
    )
    assert spec
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    sys.modules[package_name] = module
    if init_file.exists():
        # if __init__ file exists, execute it's actual import logic.
        spec.loader.exec_module(module)


def import_package(path: Path, package_name: str, enable_log: bool = True) -> None:
    if not path.exists():
        raise FileNotFoundError(f"import module path: {path}")

    if enable_log:
        log: Optional[Logger] = get_logger("init", "module")
        assert log
        log.info(f"loading Python extensions from {path}")
    else:
        log = None

    package_files: Iterable[Path]
    if path.is_file():
        # Import a single module within a package.
        package_dir = path.parent
        package_files = [path]
    else:
        # Import the entire package.
        package_dir = path
        package_files = path.glob("**/*.py")

    # import the package
    _import_root_package(package_name=package_name, path=package_dir)

    # import all the modules in the package
    for file in package_files:
        file_name = file.stem
        # skip test files and __init__.py
        if ("tests" == file.parent.stem and file_name.startswith("test_")) or (
            file.stem == "__init__"
        ):
            continue

        _import_module(
            file=file,
            root_package_name=package_name,
            package_dir=package_dir,
            log=log,
        )
