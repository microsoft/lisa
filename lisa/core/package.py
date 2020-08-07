import importlib
import os
import sys
from glob import glob

from lisa.util.logger import log


def import_module(path: str, logDetails: bool = True) -> None:

    path = os.path.realpath(path)
    if not os.path.exists(path):
        raise FileNotFoundError(path)

    package_name = os.path.basename(path)
    global packages
    packages.append(package_name)
    package_dir = os.path.dirname(path)
    sys.path.append(package_dir)
    if logDetails:
        log.info(f"loading extension from {path}")

    for file in glob(os.path.join(path, "**", "*.py"), recursive=True):
        file_name = os.path.basename(file)
        dir_name = os.path.dirname(file)
        package_dir_len = len(package_dir) + 1
        local_package_name = dir_name[package_dir_len:]
        local_package_name = local_package_name.replace("\\", ".").replace("/", ".")
        local_module_name = f".{os.path.splitext(file_name)[0]}"
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
