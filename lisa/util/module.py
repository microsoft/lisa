import importlib
import importlib.util
import sys
from pathlib import Path
from typing import Optional

from lisa.util.logger import get_logger


def import_module(
    path: Path, index: Optional[int] = None, logDetails: bool = True
) -> None:

    path = path.absolute()
    if not path.exists():
        raise FileNotFoundError(path)

    log = get_logger("init", "module")

    package_name = path.stem
    global packages
    packages.append(package_name)
    package_dir = path.parent
    sys.path.append(str(package_dir))
    if logDetails:
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
            if logDetails:
                log.debug(f"loading file: {file}")
                log.debug(
                    f"package: '{local_package_name}', "
                    f"full_module_name: '{full_module_name}' "
                )

            spec = importlib.util.spec_from_file_location(full_module_name, file)
            module = importlib.util.module_from_spec(spec)
            assert spec
            assert spec.loader
            spec.loader.exec_module(module)  # type: ignore
            sys.modules[full_module_name] = module


packages = ["lisa"]
