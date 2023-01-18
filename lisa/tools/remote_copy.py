# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import os
from pathlib import PurePath

from lisa.executable import Tool
from lisa.tools.chown import Chown
from lisa.tools.cp import Cp
from lisa.tools.ls import Ls
from lisa.tools.mkdir import Mkdir
from lisa.tools.rm import Rm
from lisa.tools.whoami import Whoami


class RemoteCopy(Tool):
    @property
    def command(self) -> str:
        return ""

    @property
    def can_install(self) -> bool:
        return False

    def _prepare_tmp_copy(
        self,
        src: PurePath,
        is_file: bool = False,
        recurse: bool = False,
    ) -> PurePath:
        # copy file/folder to a temp location
        tmp_location = PurePath("/tmp")

        if is_file:
            # we want to copy file at
            # location : <tmp_location>/<src.parent.name>/<src.name>
            tmp_dir = tmp_location / src.parent.name
            tmp_location = tmp_dir / src.name
            self.node.tools[Mkdir].create_directory(str(tmp_dir), sudo=True)
        elif not recurse:
            # we want to copy only the files in `src` folder at
            # location : <tmp_location>/<src.name>
            tmp_dir = tmp_location / src.name
            tmp_location = tmp_dir
            src = src / "*"
            self.node.tools[Mkdir].create_directory(str(tmp_dir), sudo=True)
        else:
            # we want to copy the folder at
            # location : <tmp_location>
            tmp_dir = tmp_location
            tmp_location = tmp_dir / src.name

        # copy the required file/folder to the temp directory
        self.node.tools[Cp].copy(src, tmp_dir, sudo=True, recur=recurse)

        # change the owner of the temp directory
        username = self.node.tools[Whoami].get_username()
        self.node.tools[Chown].change_owner(
            tmp_location, user=username, group=username, recurse=True
        )

        return tmp_location

    def _copy(
        self,
        src: PurePath,
        dest: PurePath,
        is_file: bool = False,
        recurse: bool = False,
    ) -> None:

        if is_file:
            destination_dir = dest
            dirs = []
            files = [src]
        else:
            # create the destination directory if it doesn't exist
            destination_dir = dest / src.name
            if not os.path.exists(destination_dir):
                os.makedirs(destination_dir)

            # get list of files and folders in the source directory
            contents = self.node.tools[Ls].list(str(src))
            dirs = (
                [PurePath(content) for content in contents if content.endswith("/")]
                if recurse
                else []
            )
            files = [
                PurePath(content) for content in contents if not content.endswith("/")
            ]

        # copy files
        for file in files:
            self.node.shell.copy_back(file, destination_dir / file.name)

        # copy sub folders
        for dir_ in dirs:
            self._copy(dir_, destination_dir, recurse=recurse)

    def copy_to_local(
        self,
        src: PurePath,
        dest: PurePath,
        recurse: bool = False,
    ) -> None:
        # check if the source is a file or a directory
        is_file = self.node.tools[Ls].is_file(src, sudo=True)

        # recurse shpuld be false for files
        recurse = recurse and not is_file

        try:
            self._copy(src, dest, recurse=recurse, is_file=is_file)
        except Exception as e:
            self._log.debug(
                f"Failed to copy files to {dest} with error: {e}, trying again "
                "with sudo"
            )

            # copy files to a temp directory with updated permissions
            tmp_location = self._prepare_tmp_copy(src, recurse=recurse, is_file=is_file)

            # copy files from the temp directory and remove the temp directory
            try:
                self._copy(tmp_location, dest, recurse=recurse, is_file=is_file)
            finally:
                self.node.tools[Rm].remove_directory(str(tmp_location), sudo=True)
