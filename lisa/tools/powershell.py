# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Any

from lisa.executable import Tool
from lisa.util import LisaException


class PowerShell(Tool):
    @property
    def command(self) -> str:
        return "powershell"

    @property
    def can_install(self) -> bool:
        # TODO: install PowerShell core on Linux.
        return False

    def run_cmdlet(
        self,
        cmdlet: str,
        force_run: bool = False,
        sudo: bool = False,
        fail_on_error: bool = True,
    ) -> str:
        result = self.run(cmdlet, force_run=force_run, sudo=sudo)
        if fail_on_error and result.exit_code != 0:
            raise LisaException(
                f"non-zero exit code {result.exit_code} from cmdlet '{cmdlet}'. "
                f"output: {result.stdout}"
            )
        return result.stdout

    def install_module(self, name: str) -> None:
        self.run_cmdlet(
            f"Install-Module -Name {name} -Scope CurrentUser "
            "-Repository PSGallery -Force"
        )

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        super()._initialize(*args, **kwargs)

        # remove security policy to run scripts
        self.run_cmdlet(
            "Set-ExecutionPolicy -ExecutionPolicy Unrestricted -Scope CurrentUser",
            fail_on_error=False,
        )
