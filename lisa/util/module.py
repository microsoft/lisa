import importlib
import sys
from pathlib import Path

from lisa.util.logger import get_logger


def import_module(path: Path, logDetails: bool = True) -> None:

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
        dir_name = file.parent
        local_package_path = dir_name.relative_to(package_dir)
        local_package_name = ".".join(local_package_path.parts)
        local_module_name = f".{file_name}"
        full_module_name = f"{local_package_name}{local_module_name}"

        if file_name.startswith("__"):
            continue

        if full_module_name not in sys.modules:
            if logDetails:
                log.debug(
                    f"loading file {file}, "
                    f"package {local_package_name}, "
                    f"full_module_name {full_module_name}, "
                    f"local_module_name {local_module_name}"
                )
            importlib.import_module(local_module_name, package=local_package_name)


packages = ["lisa"]
