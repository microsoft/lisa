# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from lisa.executable import Tool


class Cat(Tool):
    @property
    def command(self) -> str:
        return "cat"

    def _check_exists(self) -> bool:
        return True

    def read_from_file(
        self,
        file: str,
        force_run: bool = False,
        sudo: bool = False,
    ) -> str:
        # Run `cat <file>`
        result = self.run(file, force_run=force_run, sudo=sudo, shell=True)
        result.assert_exit_code(message=f"Error : {result.stdout}")
        return result.stdout
