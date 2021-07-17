# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from lisa.executable import Tool


class Sed(Tool):
    @property
    def command(self) -> str:
        return "sed"

    def replace(
        self, searched: str, replaced: str, file: str, sudo: bool = False
    ) -> None:
        # always force run, make sure it happens every time.
        searched = searched.replace('"', '\\"')
        replaced = replaced.replace('"', '\\"')
        result = self.run(
            f'-i.bak "s/{searched}/{replaced}/g" {file}',
            force_run=True,
            no_error_log=True,
            no_info_log=True,
            sudo=sudo,
            shell=True,
        )
        result.assert_exit_code(message=result.stdout)
