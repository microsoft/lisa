# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from pathlib import PurePath
from typing import TYPE_CHECKING, Any, List, Optional, Type

from lisa import LisaException
from lisa.executable import Tool
from lisa.tools.chown import Chown
from lisa.tools.cp import Cp
from lisa.tools.chmod import Chmod
from lisa.tools.ls import Ls
from lisa.tools.mkdir import Mkdir
from lisa.tools.rm import Rm
from lisa.tools.whoami import Whoami
from lisa.util import constants

if TYPE_CHECKING:
    from lisa.node import Node, RemoteNode


class RemoteCopy(Tool):
    @property
    def command(self) -> str:
        return ""

    @property
    def can_install(self) -> bool:
        return False

    def _check_exists(self) -> bool:
        return True

    def copy_to_local(
        self,
        src: PurePath,
        dest: PurePath,
        recurse: bool = False,
        sudo: bool = True,
    ) -> List[PurePath]:
        return self._copy_internal(
            src=src,
            dest=dest,
            recurse=recurse,
            is_copy_to_local=True,
            sudo=sudo,
        )

    def copy_to_remote(
        self,
        src: PurePath,
        dest: PurePath,
        recurse: bool = False,
        sudo: bool = True,
    ) -> List[PurePath]:
        return self._copy_internal(
            src=src,
            dest=dest,
            recurse=recurse,
            is_copy_to_local=False,
            sudo=sudo,
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
        sudo: bool = True,
    ) -> List[PurePath]:
        is_file = self._is_file(
            self._get_source_node(is_copy_to_local=is_copy_to_local), src, sudo
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
            tmp_location = self._prepare_tmp_copy(
                src, recurse=recurse, is_file=is_file, sudo=sudo
            )

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

    def _is_file(self, node: "Node", path: PurePath, sudo: bool = True) -> bool:
        return node.tools[Ls].is_file(path, sudo=sudo)

    def _prepare_tmp_copy(
        self,
        src: PurePath,
        is_file: bool = False,
        recurse: bool = False,
        sudo: bool = True,
    ) -> PurePath:
        # copy file/folder to a temp location
        tmp_location = PurePath("/tmp")

        if is_file:
            # we want to copy file at
            # location : <tmp_location>/<src.parent.name>/<src.name>
            tmp_dir = tmp_location / src.parent.name
            tmp_location = tmp_dir / src.name
            self.node.tools[Mkdir].create_directory(
                self.node.get_str_path(tmp_dir), sudo=sudo
            )
        elif not recurse:
            # we want to copy only the files in `src` folder at
            # location : <tmp_location>/<src.name>
            tmp_dir = tmp_location / src.name
            tmp_location = tmp_dir
            src = src / "*"
            self.node.tools[Mkdir].create_directory(
                self.node.get_str_path(tmp_dir), sudo=sudo
            )
        else:
            # we want to copy the folder at
            # location : <tmp_location>
            tmp_dir = tmp_location
            tmp_location = tmp_dir / src.name

        # copy the required file/folder to the temp directory
        self.node.tools[Cp].copy(src, tmp_dir, sudo=sudo, recur=recurse)

        self.node.tools[Ls].path_exists(self.node.get_str_path(tmp_location), sudo=sudo)

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

    def copy_between_remotes(
        self,
        src_node: "RemoteNode | Node",
        src_path: PurePath,
        dest_node: "RemoteNode | Node",
        dest_path: PurePath,
        recurse: bool = False,
    ) -> Optional[int]:
        """
        Copy a file or directory from src_node to dest_node using scp.
        The scp command is executed on the src_node, pushing to dest_node.
        Only key-based authentication is supported.
        """
        # Ensure src_path and dest_path are strings
        src_path_str = str(src_path)
        dest_path_str = str(dest_path)

        # get the node connection details for scp command
        dest_connection = dest_node.connection_info
        if not dest_connection:
            raise LisaException("destination node connection info not setup.")

        dest_user = dest_connection[constants.ENVIRONMENTS_NODES_REMOTE_USERNAME]
        dest_addr = dest_connection[constants.ENVIRONMENTS_NODES_REMOTE_ADDRESS]
        dest_key = dest_connection[constants.ENVIRONMENTS_NODES_REMOTE_PRIVATE_KEY_FILE]
        if not dest_user or not dest_addr or not dest_key:
            raise ValueError("destination node connection info inaccessible")

        # Use a temporary file for the key on src_node
        tmp_key_name = "/tmp/.lisa_dest_key"
        # Copy the dest_key to src_node (if not already present)
        if not src_node.tools[Ls].path_exists(path=tmp_key_name, sudo=False):
            self._log.debug("copying ssh key to src node")
            src_node.shell.copy(
                local_path=PurePath(dest_key),
                node_path=PurePath(tmp_key_name),
            )
            assert src_node.tools[Ls].path_exists(tmp_key_name), "copy failed"
            src_node.tools[Chmod].chmod(
                path=tmp_key_name,
                permission="0600",
                sudo=False,
            )

        self._log.debug(
            f"scp command attributes:\n"
            f"destination user: {dest_user}\n"
            f"destination IP adress: {dest_addr}\n"
            f"destination admin_key: {dest_key}\n"
            f"location of key on src: {tmp_key_name}\n"
        )
        # Prepare scp command to run on src_node, pushing to dest_node
        scp_opts = "-r" if recurse else ""
        scp_cmd = (
            f"scp {scp_opts} -i {tmp_key_name} -o StrictHostKeyChecking=no "
            f"{src_path_str} {dest_user}@{dest_addr}:{dest_path_str}"
        )
        self._log.debug(f"scp command: {scp_cmd}")
        scp_process = src_node.execute_async(
            scp_cmd,
            shell=True,
            sudo=False,
            no_info_log=False,
        )

        # Ensure to delete the ssh-key file for security
        src_node.tools[Rm].remove_file(path=tmp_key_name, sudo=False)

        scp_result = scp_process.wait_result()
        assert scp_result, "result of scp can't be 'None'."

        return scp_result.exit_code


class WindowsRemoteCopy(RemoteCopy):
    @property
    def command(self) -> str:
        return "cmd"
