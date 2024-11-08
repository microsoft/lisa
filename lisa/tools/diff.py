# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from pathlib import PurePath
from typing import Optional

from lisa.executable import Tool


class Diff(Tool):
    """
    Diff is a tool class for comparing files or directories using the 'diff' command.

    Attributes:
        command (str): The command to be executed, which is 'diff'.
        can_install (bool): Indicates whether the tool can be installed.
            Always False for this tool.

    Methods:
        _check_exists() -> bool:
            Checks if the tool exists. Always returns True for this tool.

        comparefiles(
            timeout: int = 600
            Compares two files or directories.

            Args:
                src (PurePath): The source file or directory.
                dest (PurePath): The destination file or directory.
                cwd (Optional[PurePath]): The current working directory for the command.
                Defaults to None.
                sudo (bool): Whether to run the command with sudo. Defaults to False.
                timeout (int): The timeout for the command in seconds. Defaults to 600.

            Returns:
                str: The output of the diff command.

            Raises:
                AssertionError: If the exit code of the diff command is not 0 or 1.
    """

    @property
    def command(self) -> str:
        return "diff"

    @property
    def can_install(self) -> bool:
        return False

    def comparefiles(
        self,
        src: PurePath,
        dest: PurePath,
        cwd: Optional[PurePath] = None,
        sudo: bool = False,
        timeout: int = 600,
    ) -> str:
        cmd = f"{self.node.get_str_path(src)} {self.node.get_str_path(dest)}"
        result = self.run(
            cmd,
            force_run=True,
            sudo=sudo,
            cwd=cwd,
            shell=True,
            timeout=timeout,
        )
        # Diff generated difference between FILE1 FILE2 or DIR1 DIR2 or DIR FILE
        # for FILE DIR
        # EXit status is 0 if inputs are the same. 1 if different, 2 if trouble
        result.assert_exit_code([0, 1], message=(f"Diff Error: {result.stderr}"))
        return result.stdout
