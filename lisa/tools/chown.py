# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import PurePath
from typing import List

from assertpy import assert_that

from lisa.executable import Tool


class Chown(Tool):
    @property
    def command(self) -> str:
        return "chown"

    def _check_exists(self) -> bool:
        return self.node.is_posix

    def change_owner(
        self, file: PurePath, user: str = "", group: str = "", recurse: bool = False
    ) -> None:
        # from manpage:
        # chown [OPTION]... [OWNER][:[GROUP]] FILE...
        arguments: List[str] = []

        # option for recursive chown for a folder
        if recurse:
            arguments.append("-R")

        # add [OWNER][:[GROUP]]
        if group:
            group = f":{group}"
        new_owner = f"{user}{group}"
        if new_owner:
            arguments.append(new_owner)

        # add FILE
        path_str = self.node.get_str_path(file)
        assert_that(path_str).described_as(
            "chown: filepath was empty and file is a required argument"
        ).is_true()
        arguments.append(path_str)

        # execute chown
        self.run(
            parameters=" ".join(arguments),
            shell=True,
            sudo=True,
            force_run=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                f"Chown failed to change owner for {file}"
            ),
        )
