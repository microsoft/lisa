# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from lisa.executable import Tool


class Azsecd(Tool):
    @property
    def command(self) -> str:
        return "azsecd"

    @property
    def can_install(self) -> bool:
        return False

    def install(self) -> bool:
        package_name = "azure-security"
        self.node.os.install_packages(package_name)
        return self._check_exists()
