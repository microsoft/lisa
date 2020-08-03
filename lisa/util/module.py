from glob import glob
from lisa import log
import sys


def import_module(path):
    import os

    log.info(
        "path: %s, %s", os.path.exists(path), os.path.realpath(path),
    )
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    import importlib

    package_name = os.path.basename(path)
    package_dir = os.path.dirname(path)
    sys.path.append(package_dir)
    log.info("loading extentions from %s", path)
    for file in glob(os.path.join(path, "*.py"), recursive=True):
        file_name = os.path.basename(file)
        module_name = os.path.splitext(file_name)[0]
        if file_name.startswith("__"):
            continue
        log.debug("loading file %s, module_name %s", file, module_name)
        importlib.import_module(".%s" % module_name, package=package_name)
