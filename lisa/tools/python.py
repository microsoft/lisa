# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.


from typing import Any, List, Type

from lisa.executable import Tool
from lisa.operating_system import Posix, Redhat, Ubuntu
from lisa.util import UnsupportedDistroException


class Python(Tool):
    @property
    def command(self) -> str:
        return "python3"

    @property
    def can_install(self) -> bool:
        return True

    def _install(self) -> bool:
        if isinstance(self.node.os, Posix):
            self.node.os.install_packages("python3")
        else:
            raise UnsupportedDistroException(self.node.os)

        return self._check_exists()


class Pip(Tool):
    @property
    def command(self) -> str:
        return self._command

    @property
    def can_install(self) -> bool:
        return True

    @property
    def dependencies(self) -> List[Type[Tool]]:
        return [Python]

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        if isinstance(self.node.os, Ubuntu):
            self._command = "pip3"
        else:
            self._command = "pip"

    def _install(self) -> bool:
        if isinstance(self.node.os, Redhat):
            package_name = "python-pip"
        else:
            package_name = "python3-pip"
        assert isinstance(self.node.os, Posix)
        self.node.os.install_packages(package_name)
        return self._check_exists()

    def install_packages(self, packages_name: str) -> None:
        self.run(
            f"install -q {packages_name}",
            expected_exit_code=0,
            expected_exit_code_failure_message=f"error on pip install package: "
            f"{packages_name}",
        )

    def exists_package(self, package_name: str) -> bool:
        result = self.run(f"show {package_name}", force_run=True)
        return result.exit_code == 0
