# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from pathlib import PurePath
from typing import TYPE_CHECKING, Any, List, Optional, Type

from lisa.executable import Tool
from lisa.tools.chown import Chown
from lisa.tools.cp import Cp
from lisa.tools.ls import Ls
from lisa.tools.mkdir import Mkdir
from lisa.tools.rm import Rm
from lisa.tools.whoami import Whoami

if TYPE_CHECKING:
    from lisa.node import Node


class RemoteCopy(Tool):
    @property
    def command(self) -> str:
        return ""

    @property
    def can_install(self) -> bool:
        return False

    def copy_to_local(
        self,
        src: PurePath,
        dest: PurePath,
        recurse: bool = False,
    ) -> List[PurePath]:
        return self._copy_internal(
            src=src, dest=dest, recurse=recurse, is_copy_to_local=True
        )

    def copy_to_remote(
        self,
        src: PurePath,
        dest: PurePath,
        recurse: bool = False,
    ) -> List[PurePath]:
        return self._copy_internal(
            src=src, dest=dest, recurse=recurse, is_copy_to_local=False
        )

    @classmethod
    def _windows_tool(cls) -> Optional[Type[Tool]]:
        return WindowsRemoteCopy

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        super()._initialize(*args, **kwargs)
        from lisa.node import local

        self._local_node = local()

    def _copy_internal(
        self,
        src: PurePath,
        dest: PurePath,
        recurse: bool = False,
        is_copy_to_local: bool = True,
    ) -> List[PurePath]:
        is_file = self._is_file(
            self._get_source_node(is_copy_to_local=is_copy_to_local), src
        )

        # recurse should be false for files
        recurse = recurse and not is_file

        try:
            return self._copy(
                src,
                dest,
                recurse=recurse,
                is_file=is_file,
                is_copy_to_local=is_copy_to_local,
            )
        except Exception as e:
            # use temp folder on copy to local only, because no scenario needs
            # it on copy to remote so far.
            if not is_copy_to_local:
                raise e

            self._log.debug(
                f"Failed to copy files to {dest} with error: {e}, trying again "
                "with sudo"
            )

            # copy files to a temp directory with updated permissions
            tmp_location = self._prepare_tmp_copy(src, recurse=recurse, is_file=is_file)

            # copy files from the temp directory and remove the temp directory
            try:
                return self._copy(tmp_location, dest, recurse=recurse, is_file=is_file)
            finally:
                self.node.tools[Rm].remove_directory(
                    self.node.get_str_path(tmp_location), sudo=True
                )

    def _get_source_node(self, is_copy_to_local: bool = True) -> "Node":
        if is_copy_to_local:
            return self.node
        else:
            return self._local_node

    def _get_destination_node(self, is_copy_to_local: bool = True) -> "Node":
        if is_copy_to_local:
            return self._local_node
        else:
            return self.node

    def _is_file(self, node: "Node", path: PurePath) -> bool:
        return node.tools[Ls].is_file(path, sudo=False)

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
            self.node.tools[Mkdir].create_directory(
                self.node.get_str_path(tmp_dir), sudo=True
            )
        elif not recurse:
            # we want to copy only the files in `src` folder at
            # location : <tmp_location>/<src.name>
            tmp_dir = tmp_location / src.name
            tmp_location = tmp_dir
            src = src / "*"
            self.node.tools[Mkdir].create_directory(
                self.node.get_str_path(tmp_dir), sudo=True
            )
        else:
            # we want to copy the folder at
            # location : <tmp_location>
            tmp_dir = tmp_location
            tmp_location = tmp_dir / src.name

        # copy the required file/folder to the temp directory
        self.node.tools[Cp].copy(src, tmp_dir, sudo=True, recur=recurse)

        self.node.tools[Ls].path_exists(self.node.get_str_path(tmp_location), sudo=True)

        # change the owner of the temp directory
        username = self.node.tools[Whoami].get_username()
        self.node.tools[Chown].change_owner(
            tmp_location, user=username, group=username, recurse=recurse
        )

        return tmp_location

    def _copy(
        self,
        src: PurePath,
        dest: PurePath,
        is_file: bool = False,
        recurse: bool = False,
        is_copy_to_local: bool = True,
    ) -> List[PurePath]:
        dest_files: List[PurePath] = []

        if is_copy_to_local:
            src_node = self.node
            dest_node = self._local_node
        else:
            src_node = self._local_node
            dest_node = self.node

        if is_file:
            destination_dir = dest
            dirs = []
            source_files = [src]
        else:
            # create the destination directory if it doesn't exist
            destination_dir = dest / src.name
            ls = dest_node.tools[Ls]
            if not ls.path_exists(dest_node.get_str_path(destination_dir)):
                dest_node.tools[Mkdir].create_directory(
                    dest_node.get_str_path(destination_dir)
                )

            # get list of files and folders in the source directory
            contents = src_node.tools[Ls].list(src_node.get_str_path(src))
            dirs = (
                [PurePath(content) for content in contents if content.endswith("/")]
                if recurse
                else []
            )
            source_files = [
                PurePath(content) for content in contents if not content.endswith("/")
            ]

        # copy files
        for source_file in source_files:
            dest_files.append(destination_dir / source_file.name)
            if is_copy_to_local:
                self.node.shell.copy_back(
                    source_file,
                    destination_dir / source_file.name,
                )
            else:
                self.node.shell.copy(source_file, destination_dir / source_file.name)

        # copy sub folders
        for dir_ in dirs:
            dest_files.extend(self._copy(dir_, destination_dir, recurse=recurse))

        return dest_files


class WindowsRemoteCopy(RemoteCopy):
    @property
    def command(self) -> str:
        return "cmd"
