# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from lisa.executable import Tool
from lisa.util import LisaException


class Readlink(Tool):
    @property
    def command(self) -> str:
        return "readlink"

    @property
    def can_install(self) -> bool:
        return False

    def _read_link(
        self,
        path: str,
        canonicalize: bool = False,
        force_run: bool = True,
        sudo: bool = False,
        no_error_log: bool = False,
    ) -> str:
        """
        Read symbolic link or canonical file name.
        """
        args = "-f " if canonicalize else ""
        args += path

        result = self.run(
            args,
            force_run=force_run,
            sudo=sudo,
            shell=True,
        )

        if result.exit_code != 0:
            if not no_error_log:
                raise LisaException(f"Failed to read link '{path}': {result.stderr}")
            return ""

        return result.stdout.strip()

    def get_target(
        self,
        path: str,
        sudo: bool = False,
        no_error_log: bool = False,
    ) -> str:
        """
        Get the immediate target of a symbolic link (without following further links).
        """
        return self._read_link(
            path=path,
            canonicalize=False,
            sudo=sudo,
            no_error_log=no_error_log,
        )

    def get_canonical_path(
        self,
        path: str,
        sudo: bool = False,
        no_error_log: bool = False,
    ) -> str:
        """
        Get the canonical absolute path by following all symbolic links
        in every component of the given name recursively.
        """
        return self._read_link(
            path=path,
            canonicalize=True,
            sudo=sudo,
            no_error_log=no_error_log,
        )
