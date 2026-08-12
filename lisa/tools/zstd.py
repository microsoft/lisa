# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from shlex import quote
from typing import cast

from lisa.executable import Tool
from lisa.operating_system import Posix
from lisa.util import LisaException


class Zstd(Tool):
    @property
    def command(self) -> str:
        return "zstd"

    @property
    def can_install(self) -> bool:
        return True

    def _install(self) -> bool:
        posix_os = cast(Posix, self.node.os)
        posix_os.install_packages(self.command)
        return self._check_exists()

    def decompress(self, file: str, output_file: str = "", sudo: bool = False) -> str:
        if not output_file:
            if not file.endswith(".zst"):
                raise LisaException(
                    f"An output file is required to decompress non-.zst file {file}."
                )
            output_file = file[:-4]

        self.run(
            f"-d -f -o {quote(output_file)} {quote(file)}",
            shell=False,
            force_run=True,
            sudo=sudo,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                f"Failed to decompress {file} to {output_file}."
            ),
        )
        return output_file
