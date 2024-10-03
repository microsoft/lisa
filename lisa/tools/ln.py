# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from lisa.executable import Tool


class Ln(Tool):
    @property
    def command(self) -> str:
        return "ln"

    @property
    def can_install(self) -> bool:
        return False

    def create_link(
        self,
        target: str,
        link: str,
        is_symbolic: bool = True,
        force: bool = False,
    ) -> None:
        cmd = ""
        if is_symbolic:
            cmd += " -s "
        if force:
            cmd += " -f "
        cmd += f"{target} {link}"
        self.run(
            cmd,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                f"cannot create link {link} for {target}"
            ),
        )
