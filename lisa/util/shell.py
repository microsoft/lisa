# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import contextlib
import logging
import os
import pathlib
import posixpath
import re
import shutil
import socket
import stat as stat_module
import sys
import time
import uuid
from functools import partial
from pathlib import Path, PurePath, PureWindowsPath
from time import sleep
from typing import (
    Any,
    Callable,
    Dict,
    Iterator,
    List,
    Mapping,
    Optional,
    Sequence,
    TextIO,
    Tuple,
    TypeVar,
    Union,
    cast,
)

import icontract
import paramiko
import spur  # type: ignore
import temppathlib
from func_timeout import FunctionTimedOut, func_set_timeout  # type: ignore
from paramiko.ssh_exception import NoValidConnectionsError, SSHException

from lisa import development, schema
from lisa.util import (
    InitializableMixin,
    LisaException,
    SshSpawnTimeoutException,
    TcpConnectionException,
    filter_ansi_escape,
)

from .logger import Logger, get_logger
from .perf_timer import create_timer

T = TypeVar(
    'T'
)


class ReconnectingSFTP:
    """Open automatically a new paramiko.SFTP on connection failure."""

    # pylint: disable=too-many-public-methods

    def __init__(self, sftp_opener: Callable[[], paramiko.SFTP], max_retries: int = 10,
                 retry_period: float = 0.1) -> None:
        """
        Iniialize.

        :param sftp_opener: method to open a new SFTP connection
        :param max_retries: maximum number of retries before raising ConnectionError
        :param retry_period: how long to wait between two retries; in seconds
        """
        self.__sftp_opener = sftp_opener
        self.max_retries: int = max_retries
        self.retry_period: float = retry_period

        self._sftp: Optional[paramiko.SFTP] = None

        # last recorded working directory
        self.last_working_directory: Optional[str] = None

    def close(self) -> None:
        """Close the the underlying paramiko SFTP client."""
        if self._sftp is not None:
            self._sftp.close()
            self._sftp = None

    def __enter__(self) -> 'ReconnectingSFTP':
        """Return self prepared in a constructor upon enter."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Close upon exist."""
        self.close()

    def __wrap(self, method: Callable[[paramiko.SFTP], T]) -> T:
        """
        Wrap the SFTP method in a retry loop.

        Open an SFTP connection, if necessary,
        and change to the last recorded working directory before
        executing the method.

        :param method: to be wrapped
        :return: method's result
        """
        last_err: Optional[Union[socket.error, EOFError]] = None

        success = False
        for _ in range(0, self.max_retries):
            try:
                if self._sftp is None:
                    self._sftp = self.__sftp_opener()
                assert self._sftp is not None

                if self._sftp.sock.closed:
                    self._sftp = self.__sftp_opener()
                assert not self._sftp.sock.closed

                if self.last_working_directory is not None:
                    self._sftp.chdir(path=self.last_working_directory)

                success = True

            except (socket.error, EOFError) as err:
                last_err = err

                if self._sftp is not None:
                    self._sftp.close()
                    self._sftp = None

                time.sleep(self.retry_period)

        if not success:
            raise ConnectionError(
                "Failed to execute an SFTP command after {} retries"
                " due to connection failure: {}".format(
                    self.max_retries, last_err))

        return method(self._sftp)  # type: ignore

    def chmod(self, path: str, mode: int) -> None:
        """See paramiko.SFTP documentation."""
        return self.__wrap(method=lambda sftp: sftp.chmod(path, mode))

    def chown(self, path: str, uid: int, gid: int) -> None:
        """See paramiko.SFTP documentation."""
        return self.__wrap(method=lambda sftp: sftp.chown(path, uid, gid))

    def stat(self, path: str) -> paramiko.sftp_attr.SFTPAttributes:
        """See paramiko.SFTP documentation."""
        return self.__wrap(method=lambda sftp: sftp.stat(path))

    def rmdir(self, path: str) -> None:
        """See paramiko.SFTP documentation."""
        return self.__wrap(method=lambda sftp: sftp.rmdir(path))

    def listdir_attr(self, path: str = '.') -> List[paramiko.SFTPAttributes]:
        """See paramiko.SFTP documentation."""
        return self.__wrap(method=lambda sftp: sftp.listdir_attr(path))

    def remove(self, path: str) -> None:
        """See paramiko.SFTP documentation."""
        return self.__wrap(method=lambda sftp: sftp.remove(path))

    unlink = remove

    def posix_rename(self, oldpath: str, newpath: str) -> None:
        """See paramiko.SFTP documentation."""
        return self.__wrap(method=lambda sftp: sftp.posix_rename(oldpath, newpath))

    def mkdir(self, path: str, mode: int = 0o777) -> None:
        """See paramiko.SFTP documentation."""
        return self.__wrap(method=lambda sftp: sftp.mkdir(path, mode))

    def lstat(self, path: str) -> paramiko.sftp_attr.SFTPAttributes:
        """See paramiko.SFTP documentation."""
        return self.__wrap(method=lambda sftp: sftp.lstat(path))

    def symlink(self, source: str, dest: str) -> None:
        """See paramiko.SFTP documentation."""
        return self.__wrap(method=lambda sftp: sftp.symlink(source, dest))

    def put(
        self,
        localpath: str,
        remotepath: str,
        callback: Optional[Callable[[int, int], Any]] = None,
        confirm: bool = True,
    ) -> paramiko.sftp_attr.SFTPAttributes:
        """See paramiko.SFTP documentation."""
        return self.__wrap(method=lambda sftp: sftp.put(localpath, remotepath, callback, confirm))

    def get(
        self,
        remotepath: str,
        localpath: str,
        callback: Optional[Callable[[int, int], Any]] = None,
    ) -> None:
        """See paramiko.SFTP documentation."""
        return self.__wrap(method=lambda sftp: sftp.get(remotepath, localpath, callback))


class SshShellWithSFTP(icontract.DBC):
    def __init__(self,
                 spur_ssh_shell: spur.SshShell,
                 sftp: Union[paramiko.SFTP, ReconnectingSFTP],
                 close_spur_shell: bool = True,
                 close_sftp: bool = True) -> None:
        """
        Initialize the SSH wrapper with the given underlying spur SshShell and the SFTP client.

        :param spur_ssh_shell: to wrap
        :param sftp: to wrap
        :param close_spur_shell: if set, closes spur shell when the wrapper is closed
        :param close_sftp: if set, closes SFTP when this wrapper is closed
        """
        self._spur = spur_ssh_shell
        self._sftp = sftp

        self.close_spur_shell = close_spur_shell
        self.close_sftp = close_sftp

        self.hostname = spur_ssh_shell._hostname
        self.port = spur_ssh_shell._port

    @property
    def sftp(self) -> Union[paramiko.SFTP, ReconnectingSFTP]:
        """Return the SFTP client."""
        return self._sftp

    def close(self) -> None:
        """Close the underlying spur shell and SFTP (if ``close_spur_shell`` and ``close_sftp``, respectively)."""
        try:
            if self.close_spur_shell:
                self._spur.close()
        finally:
            if self.close_sftp:
                self._sftp.close()

    def exists(self, remote_path: Union[str, pathlib.Path]) -> bool:
        """
        Check if a file exists on a remote machine.

        :param sftp: SFTP client
        :param remote_path: to the file
        :return: True if the file exists on the remote machine at `remote_path`
        """
        sftp = self._sftp
        if isinstance(remote_path, str):
            rmt_pth_str = remote_path
        elif isinstance(remote_path, pathlib.Path):
            rmt_pth_str = remote_path.as_posix()
        else:
            raise NotImplementedError("Unhandled type of remote path: {}".format(type(remote_path)))

        permerr: Optional[PermissionError] = None
        try:
            sftp.stat(rmt_pth_str)
            return True
        except FileNotFoundError:
            return False
        except PermissionError as err:
            permerr = err

        if permerr:
            raise permerr

        raise AssertionError("Expected to raise before.")

    # flake8: noqa: C901
    def mkdir(self,
              remote_path: Union[str, pathlib.Path],
              mode: int = 0o777,
              parents: bool = False,
              exist_ok: bool = False) -> None:
        """
        Create the remote directory with the given SFTP client.
        """
        # pylint: disable=too-many-branches, too-many-locals
        if isinstance(remote_path, str):
            rmt_pth = pathlib.Path(os.path.normpath(remote_path))
        elif isinstance(remote_path, pathlib.Path):
            rmt_pth = pathlib.Path(os.path.normpath(remote_path.as_posix()))
        else:
            raise NotImplementedError(
                "Unhandled type of remote path: {}".format(type(remote_path)))

        if self.exists(remote_path=remote_path):
            if not exist_ok:
                raise FileExistsError(
                    "The remote directory already exists: {}".format(remote_path))
            else:
                return

        oserr: Optional[OSError] = None

        if not parents:
            if not self.exists(remote_path=rmt_pth.parent):
                raise FileNotFoundError(
                    "The parent remote directory {} does not exist, parents=False and we need to mkdir: {}".format(
                        rmt_pth.parent, remote_path))

            try:
                self.sftp.mkdir(path=rmt_pth.as_posix(), mode=mode)
            except OSError as err:
                oserr = err

            if oserr is not None:
                msg = "Failed to create the directory {}: {}".format(rmt_pth.as_posix(), oserr)
                if isinstance(oserr, PermissionError):
                    raise PermissionError(msg)
                else:
                    raise OSError(msg)
        else:
            directories = list(reversed(rmt_pth.parents))
            directories.append(rmt_pth)

            root = pathlib.Path('/')

            for directory in directories:
                if directory == root:
                    continue

                directory_exists = self.exists(remote_path=directory)
                if directory_exists:
                    continue

                try:
                    self.sftp.mkdir(path=directory.as_posix(), mode=mode)
                except OSError as err:
                    oserr = err

                if oserr is not None:
                    msg = "Failed to create the directory {}: {}".format(directory.as_posix(), oserr)
                    if isinstance(oserr, PermissionError):
                        raise PermissionError(msg)
                    else:
                        raise OSError(msg)

    @contextlib.contextmanager
    def _temporary_file_deleted_after_cm_exit(self) -> Iterator[temppathlib.NamedTemporaryFile]:
        """
        Generate a temporary file that is deleted only on context exit.

        The file is **not** deleted when you invoke close() on it.

        :return: context manager around a temporary file
        """
        fid = temppathlib.NamedTemporaryFile(delete=False)

        # Close the file so that it can be reused in different function calls
        fid.close()

        try:
            yield fid
        finally:
            try:
                fid.path.unlink()
            except FileNotFoundError:
                pass

    def _path_to_posix_str(self, path: Union[str, pathlib.Path]) -> str:
        """
        Convert the path to a string representation in POSIX.

        :param path: to be converted
        :return: string representing the path in POSIX
        """
        if isinstance(path, str):
            result = path
        elif isinstance(path, pathlib.Path):
            result = path.as_posix()
        else:
            raise TypeError("Unexpected type of path {}: {}".format(path, type(path)))

        return result

    def remove(self,
        remote_path: Union[str, pathlib.Path],
        recursive: bool = False,
    ) -> None:
        """
        Remove a file or a directory.

        :param remote_path: to a file or a directory
        :param recursive:
            if set, removes the directory recursively. 
            This parameter has no effect if remote_path is not a directory.
        :return:
        """
        rmt_pth_str = self._path_to_posix_str(path=remote_path)

        a_stat = self.stat(remote_path=rmt_pth_str)
        if a_stat is None:
            raise FileNotFoundError(
                "Remote file does not exist and thus can not be removed: {}".format(rmt_pth_str)
            )

        if a_stat is not None and not stat_module.S_ISDIR(a_stat.st_mode): # type: ignore
            self._sftp.remove(rmt_pth_str)
            return

        if not recursive:
            attrs = self._sftp.listdir_attr(rmt_pth_str)

            if len(attrs) > 0:
                raise OSError(
                    "The remote directory is not empty and the recursive flag was not set: {}".format(rmt_pth_str))

            self._sftp.rmdir(rmt_pth_str)
            return

        # Remove all files in the first step, then remove all the directories in a second step
        stack1: List[str] = []
        stack2: List[str] = []

        # First step: remove all files
        stack1.append(rmt_pth_str)

        while stack1:
            pth = stack1.pop()
            stack2.append(pth)

            for attr in self._sftp.listdir_attr(pth):
                subpth = posixpath.join(pth, attr.filename)

                if stat_module.S_ISDIR(attr.st_mode): #type: ignore
                    stack1.append(subpth)
                else:
                    try:
                        self._sftp.remove(path=subpth)
                    except OSError as err:
                        raise OSError("Failed to remove the remote file while recursively removing {}: {}".format(
                            rmt_pth_str, subpth)) from err

        # Second step: remove all directories
        while stack2:
            pth = stack2.pop()

            try:
                self._sftp.rmdir(path=pth)
            except OSError as err:
                raise OSError("Failed to remove the remote directory while recursively removing {}: {}".format(
                    rmt_pth_str, pth)) from err

    def run(self,
        command: Sequence[str],
        cwd: Optional[Union[str, pathlib.Path]] = None,
        update_env: Optional[Mapping[str, str]] = None,
        allow_error: bool = False,
        stdout: Optional[TextIO] = None,
        stderr: Optional[TextIO] = None,
        encoding: str = 'utf-8',
        use_pty: bool = False,
    ) -> spur.results.ExecutionResult:
        """
        Run a command on the remote instance and waits for it to complete.
        """
        # pylint: disable=too-many-arguments

        return self.spawn(
            command=command,
            cwd=cwd,
            update_env=update_env,
            allow_error=allow_error,
            stdout=stdout,
            stderr=stderr,
            encoding=encoding,
            use_pty=use_pty).wait_for_result()

    def chmod(self, remote_path: Union[str, pathlib.Path], mode: int) -> None:
        """
        Change the permission mode of the file.

        :param remote_path: to the file
        :param mode: permission mode
        :return:
        """
        rmt_pth_str = self._path_to_posix_str(path=remote_path)

        try:
            self._sftp.chmod(path=rmt_pth_str, mode=mode)
        except FileNotFoundError as err:
            raise FileNotFoundError("Remote file to be chmod'ed does not exist: {}".format(rmt_pth_str)) from err

    def is_dir(self, remote_path: Union[str, pathlib.Path]) -> bool:
        """
        Check whether the remote path is a directory.

        :param remote_path: path to the remote file or directory
        :return: True if the remote path is a directory
        :raise: FileNotFound if the remote path does not exist
        """
        rmt_pth_str = self._path_to_posix_str(path=remote_path)

        a_stat = self.stat(remote_path=rmt_pth_str)
        if a_stat is None:
            raise FileNotFoundError("Remote file does not exist: {}".format(rmt_pth_str))

        return stat_module.S_ISDIR(a_stat.st_mode) #type: ignore

    def is_symlink(self, remote_path: Union[str, pathlib.Path]) -> bool:
        """
        Check whether the remote path is a symlink.

        :param remote_path: path to the remote file or directory
        :return: True if the remote path is a directory
        :raise: FileNotFound if the remote path does not exist
        """
        rmt_pth_str = self._path_to_posix_str(path=remote_path)

        try:
            a_lstat = self._sftp.lstat(path=rmt_pth_str)
            return stat_module.S_ISLNK(a_lstat.st_mode) # type: ignore

        except FileNotFoundError as err:
            raise FileNotFoundError(
                "Remote file does not exist: {}".format(rmt_pth_str)) from err

    def get(self,
            remote_path: Union[str, pathlib.Path],
            local_path: Union[str, pathlib.Path],
            create_directories: bool = True,
            consistent: bool = True) -> None:
        """
        Get a file from the remote host.
        """
        rmt_pth_str = (
            remote_path if isinstance(remote_path, str) else remote_path.as_posix()
        )

        loc_pth = (
            local_path if isinstance(local_path, pathlib.Path)
            else pathlib.Path(local_path)
        )

        if create_directories:
            loc_pth.parent.mkdir(mode=0o777, exist_ok=True, parents=True)

        if consistent:
            with self._temporary_file_deleted_after_cm_exit() as tmp:
                self._sftp.get(remotepath=rmt_pth_str, localpath=str(tmp.path))
                shutil.move(src=str(tmp.path), dst=str(loc_pth))
        else:
            self._sftp.get(remotepath=rmt_pth_str, localpath=str(loc_pth))

    def put(self,
            local_path: Union[str, pathlib.Path],
            remote_path: Union[str, pathlib.Path],
            create_directories: bool = True,
            consistent: bool = True) -> None:
        # pylint: disable=too-many-branches
        # pylint: disable=too-many-statements
        rmt_pth = remote_path if isinstance(remote_path, pathlib.Path) else pathlib.Path(remote_path)

        loc_pth_str = local_path if isinstance(local_path, str) else str(local_path)

        if create_directories:
            self.mkdir(remote_path=rmt_pth.parent, mode=0o777, parents=True, exist_ok=True)

        oserr: Optional[OSError] = None

        if not consistent:
            try:
                self._sftp.put(localpath=loc_pth_str, remotepath=rmt_pth.as_posix())
            except OSError as err:
                oserr = err

            if oserr is not None:
                msg = "Failed to put the local file {} to the remote path {}: {}".format(
                    local_path, rmt_pth.as_posix(), oserr)
                if isinstance(oserr, PermissionError):
                    raise PermissionError(msg)
                else:
                    raise OSError(msg)

        else:
            tmp_pth = rmt_pth.parent / (rmt_pth.name + ".{}.tmp".format(uuid.uuid4()))
            success = False

            try:
                try:
                    self._sftp.put(localpath=loc_pth_str, remotepath=tmp_pth.as_posix())
                except OSError as err:
                    oserr = err

                if oserr is not None:
                    msg = "Failed to put the local file {} to the remote temporary path {}: {}".format(
                        local_path, tmp_pth, oserr)

                    if isinstance(oserr, PermissionError):
                        raise PermissionError(msg)
                    else:
                        raise OSError(msg)

                # apply the same permissions to the temporary file
                stat: Optional[paramiko.SFTPAttributes] = None
                try:
                    stat = self._sftp.stat(rmt_pth.as_posix())
                except FileNotFoundError:
                    pass

                if stat is not None:
                    try:
                        self._sftp.chmod(path=tmp_pth.as_posix(), mode=stat.st_mode) # type: ignore
                        self._sftp.chown(path=tmp_pth.as_posix(), uid=stat.st_uid, gid=stat.st_gid) # type: ignore
                    except OSError as err:
                        oserr = err

                    if oserr is not None:
                        msg = ("Failed to change the permissions and ownership of "
                               "the remote temporary path {}: {}").format(tmp_pth, oserr)
                        if isinstance(oserr, PermissionError):
                            raise PermissionError(msg)
                        else:
                            raise OSError(msg)

                ioerr: Optional[IOError] = None
                try:
                    self._sftp.posix_rename(oldpath=tmp_pth.as_posix(), newpath=rmt_pth.as_posix())
                except IOError as err:
                    ioerr = err

                if ioerr is not None:
                    raise IOError("Failed to rename the remote temporary file {} to the remote path {}: {}".format(
                        tmp_pth, remote_path, ioerr))

                success = True
            finally:
                if not success and self.exists(remote_path=tmp_pth):
                    self._sftp.unlink(path=tmp_pth.as_posix())

    def spawn(self,
              command: Sequence[str],
              update_env: Optional[Mapping[str, str]] = None,
              store_pid: bool = False,
              cwd: Optional[Union[str, pathlib.Path]] = None,
              stdout: Optional[TextIO] = None,
              stderr: Optional[TextIO] = None,
              encoding: str = 'utf-8',
              use_pty: bool = False,
              allow_error: bool = False) -> spur.ssh.SshProcess:
        """
        Spawn a remote process.

        From https://github.com/mwilliamson/spur.py/blob/0.3.20/README.rst
        """
        # pylint: disable=too-many-arguments

        update_env_dict = {} if update_env is None else update_env

        if cwd is None:
            resolved_cwd = None
        elif isinstance(cwd, str):
            resolved_cwd = cwd
        elif isinstance(cwd, pathlib.Path):
            resolved_cwd = cwd.as_posix()
        else:
            raise NotImplementedError("Unhandled type of cwd: {}".format(type(cwd)))

        return self._spur.spawn(
            command=command,
            cwd=resolved_cwd,
            update_env=update_env_dict,
            store_pid=store_pid,
            allow_error=allow_error,
            stdout=stdout,
            stderr=stderr,
            encoding=encoding,
            use_pty=use_pty)

    def stat(self, remote_path: Union[str, pathlib.Path]) -> Optional[paramiko.SFTPAttributes]:
        """
        Stat the given remote path.

        :param remote_path: to the file
        :return: stats of the file; None if the file does not exist
        """
        result: Optional[paramiko.SFTPAttributes] = None

        rmt_pth_str = self._path_to_posix_str(path=remote_path)

        try:
            result = self._sftp.stat(path=rmt_pth_str)
        except FileNotFoundError:
            pass

        return result


_get_jump_box_logger = partial(get_logger, name="jump_box")


# (Failed to parse line 'b'/etc/profile.d/vglrun.sh: line 3: lspci: command not found'' as integer)  # noqa: E501
# (Failed to parse line 'b"touch: cannot touch '/tmp/version-updated': Permission denied"' as integer)  # noqa: E501
# (Failed to parse line 'b'/etc/profile.d/clover.sh: line 10: /opt/clover/bin/prepare-hostname.sh: Permission denied'' as integer)  # noqa: E501
_spawn_initialization_error_pattern = re.compile(
    r"(Failed to parse line \'b[\'\"](?P<linux_profile_error>.*?)[\'\"]\' as integer)"
)


def minimal_escape_sh(value: str) -> str:
    return value.replace("'", "'\\''")


def minimal_generate_run_command(  # type: ignore
    self,
    command_args: str,
    store_pid: bool,
    cwd: Optional[str] = None,
    update_env: Optional[Dict[str, str]] = None,
    new_process_group: bool = False,
) -> str:
    return " ".join(map(minimal_escape_sh, command_args))


def wait_tcp_port_ready(
    address: str, port: int, log: Optional[Logger] = None, timeout: int = 300
) -> Tuple[bool, int]:
    """
    return is ready or not
    """
    is_ready: bool = False
    # TODO: may need to support IPv6.
    times: int = 0
    result: int = 0

    if development.is_mock_tcp_ping():
        # If it's True, it means the direct connection doesn't work. Return a
        # mock value for test purpose.
        return True, 0

    timeout_timer = create_timer()
    while timeout_timer.elapsed(False) < timeout:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as tcp_socket:
            try:
                result = tcp_socket.connect_ex((address, port))
                if result == 0:
                    is_ready = True
                    break
                else:
                    if times % 10 == 0 and log:
                        log.debug(
                            f"cannot connect to {address}:{port}, "
                            f"error code: {result}, current try: {times + 1},"
                            f" elapsed: {timeout_timer.elapsed(False)} "
                            f"(timeout on {timeout}). retrying..."
                        )
                    sleep(1)
                    times += 1
            except Exception as e:
                raise LisaException(f"failed to connect to {address}:{port}: {e}")
    return is_ready, result


class WindowsShellType(object):
    """
    Windows command generator
    Support get pid, set envs, and cwd
    Doesn't support kill, it needs overwrite spur.SshShell
    """

    supports_which = False

    def generate_run_command(
        self,
        command_args: List[str],
        store_pid: bool = False,
        cwd: Optional[str] = None,
        update_env: Optional[Dict[str, str]] = None,
        new_process_group: bool = False,
    ) -> str:
        commands = []

        if store_pid:
            commands.append(
                'powershell "(gwmi win32_process|? processid -eq $pid).parentprocessid"'
                " &&"
            )

        if cwd is not None:
            commands.append(f"cd {cwd} 2>&1 && echo spur-cd: 0 ")
            commands.append("|| echo spur-cd: 1 && exit 1 &")

        if update_env:
            update_env_commands = [
                "set {0}={1}".format(key, value) for key, value in update_env.items()
            ]
            commands += f"{'& '.join(update_env_commands)}& "

        if cwd is not None:
            commands.append(f"pushd {cwd} & ")
            commands.append(" ".join(command_args))
        else:
            commands.append(" ".join(command_args))
        return " ".join(commands)


# retry strategy is the same as spurplus.connect_with_retries.
def try_connect(
    connection_info: schema.ConnectionInfo,
    ssh_timeout: int = 300,
    sock: Optional[Any] = None,
) -> Any:
    # spur always run a posix command and will fail on Windows.
    # So try with paramiko firstly.
    paramiko_client = paramiko.SSHClient()

    # Use base policy, do nothing on host key. The host key shouldn't be saved
    # locally, or make any warning message. The IP addresses in cloud may be
    # reused by different servers. If they are saved, there will be conflict
    # error in paramiko.
    paramiko_client.set_missing_host_key_policy(paramiko.MissingHostKeyPolicy())

    # wait for ssh port to be ready
    timeout_start = time.time()
    while time.time() < timeout_start + ssh_timeout:
        try:
            paramiko_client.connect(
                hostname=connection_info.address,
                port=connection_info.port,
                username=connection_info.username,
                password=connection_info.password,
                key_filename=connection_info.private_key_file,
                banner_timeout=10,
                sock=sock,
            )

            stdin, stdout, _ = paramiko_client.exec_command("cmd\n")
            # Flush commands and prevent more writes
            stdin.flush()

            # Give it some time to process the command, otherwise reads on
            # stdout on calling contexts have been seen having empty strings
            # from stdout, on Windows. There is a certain 3s penalty on Linux
            # systems, as it's never ready for that (nonexisting) command, but
            # that should only happen once per node (not per command)
            tries = 3
            while not stdout.channel.recv_ready() and tries:
                sleep(1)
                tries -= 1

            stdin.channel.shutdown_write()
            paramiko_client.close()

            return stdout
        except SSHException as e:
            # socket is open, but SSH service not responded
            if (
                str(e) == "Error reading SSH protocol banner"
                or str(e) == "SSH session not active"
            ):
                sleep(1)
                continue
        except (NoValidConnectionsError, ConnectionResetError, TimeoutError):
            # ssh service is not ready
            sleep(1)
            continue

    # raise exception if ssh service is not ready
    raise LisaException(f"ssh connection cannot be established: {connection_info}")


# paramiko stuck on get command output of 'fortinet' VM, and spur hide timeout of
# exec_command. So use an external timeout wrapper to force timeout.
# some images needs longer time to set up ssh connection.
# e.g. Oracle Oracle-Linux 7.5 7.5.20181207
# e.g. qubole-inc qubole-data-service default-img 0.7.4
@func_set_timeout(20)  # type: ignore
def _spawn_ssh_process(shell: spur.ssh.SshShell, **kwargs: Any) -> spur.ssh.SshProcess:
    return shell.spawn(**kwargs)


class SshShell(InitializableMixin):
    def __init__(self, connection_info: schema.ConnectionInfo) -> None:
        super().__init__()
        self.is_remote = True
        self.connection_info = connection_info
        self._inner_shell: Optional[spur.SshShell] = None
        self._jump_boxes: List[Any] = []
        self._jump_box_sock: Any = None
        self.is_sudo_required_password: bool = False
        self.password_prompts: List[str] = []
        self.bash_prompt: str = ""
        self.spawn_initialization_error_string = ""

        paramiko_logger = logging.getLogger("paramiko")
        paramiko_logger.setLevel(logging.WARN)

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        is_ready, tcp_error_code = wait_tcp_port_ready(
            self.connection_info.address, self.connection_info.port
        )
        if not is_ready:
            raise TcpConnectionException(
                self.connection_info.address,
                self.connection_info.port,
                tcp_error_code,
            )

        sock = self._establish_jump_boxes(
            address=self.connection_info.address,
            port=self.connection_info.port,
        )

        try:
            stdout = try_connect(self.connection_info, sock=sock)
        except Exception as identifier:
            raise LisaException(
                f"failed to connect SSH "
                f"[{self.connection_info.address}:{self.connection_info.port}], "
                f"{identifier.__class__.__name__}: {identifier}"
            )

        self._close_jump_boxes()

        # Some windows doesn't end the text stream, so read first line only.
        # it's  enough to detect os.
        stdout_content = stdout.readline()
        stdout.close()

        if stdout_content and "Windows" in stdout_content:
            self.is_posix = False
            shell_type = WindowsShellType()
        else:
            self.is_posix = True
            shell_type = spur.ssh.ShellTypes.sh

        sock = self._establish_jump_boxes(
            address=self.connection_info.address,
            port=self.connection_info.port,
        )

        # According to paramiko\client.py connect() function,
        # when password and private_key_file all exist, private key is attempted
        # with high priority for authentication when connecting to a remote node
        spur_kwargs = {
            "hostname": self.connection_info.address,
            "port": self.connection_info.port,
            "username": self.connection_info.username,
            "password": self.connection_info.password,
            "private_key_file": self.connection_info.private_key_file,
            "missing_host_key": spur.ssh.MissingHostKey.accept,
            # There are too many servers in cloud, and they may reuse the same
            # IP in different time. If so, there is host key conflict. So do not
            # load host keys to avoid this kind of error.
            "load_system_host_keys": False,
            "sock": sock,
        }

        spur_ssh_shell = spur.SshShell(shell_type=shell_type, **spur_kwargs)
        sftp = ReconnectingSFTP(
            sftp_opener=spur_ssh_shell._open_sftp_client
        )
        self._inner_shell = SshShellWithSFTP(spur_ssh_shell=spur_ssh_shell, sftp=sftp)

    def close(self) -> None:
        if self._inner_shell:
            self._inner_shell.close()
            # after closed, can be reconnect
            self._inner_shell = None
        self._is_initialized = False

        self._close_jump_boxes()

    @property
    def is_connected(self) -> bool:
        is_inner_shell_ready = False
        if self._inner_shell:
            is_inner_shell_ready = True
        return is_inner_shell_ready

    def spawn(
        self,
        command: Sequence[str],
        update_env: Optional[Mapping[str, str]] = None,
        store_pid: bool = False,
        cwd: Optional[Union[str, Path]] = None,
        stdout: Any = None,
        stderr: Any = None,
        encoding: str = "utf-8",
        use_pty: bool = True,
        allow_error: bool = True,
    ) -> spur.ssh.SshProcess:
        self.initialize()
        assert self._inner_shell
        have_tried_minimal_type = False

        while True:
            try:
                if self._inner_shell._spur._shell_type == spur.ssh.ShellTypes.minimal:
                    # minimal shell type doesn't support store_pid
                    store_pid = False
                process: spur.ssh.SshProcess = _spawn_ssh_process(
                    self._inner_shell,
                    command=command,
                    update_env=update_env,
                    store_pid=store_pid,
                    cwd=cwd,
                    stdout=stdout,
                    stderr=stderr,
                    encoding=encoding,
                    use_pty=use_pty,
                    allow_error=allow_error,
                )
                break
            except FunctionTimedOut:
                raise SshSpawnTimeoutException(
                    f"The remote node is timeout on execute {command}. "
                    f"Possible reasons are, "
                    "the process wait for inputs, "
                    "the paramiko/spur not support the shell of node."
                )
            except spur.errors.CommandInitializationError as identifier:
                # Some publishers images, such as azhpc-desktop, javlinltd and
                # vfunctiontechnologiesltd, there might have permission errors when
                # scripts under /etc/profile.d directory are executed at startup of
                # the bash shell for a non-root user. Then calling spawn to run any
                # Linux commands might raise CommandInitializationError.
                # The error messages are like: "Error while initializing command. The
                # most likely cause is an unsupported shell. Try using a minimal shell
                # type when calling 'spawn' or 'run'. (Failed to parse line 'b'
                # /etc/profile.d/clover.sh:line 10:/opt/clover/bin/prepare-hostname.sh:
                # Permission denied'' as integer)"
                # Except CommandInitializationError then use minimal shell type.
                if not have_tried_minimal_type:
                    self._inner_shell._spur._shell_type = spur.ssh.ShellTypes.minimal
                    have_tried_minimal_type = True
                    matched = _spawn_initialization_error_pattern.search(
                        str(identifier)
                    )
                    if matched:
                        self.spawn_initialization_error_string = matched.group(
                            "linux_profile_error"
                        )
                    else:
                        # Dynamically override that object's method. Here,
                        # we don't enclose every shell token under single
                        # quotes anymore. That's an assumption from spur
                        # that minimal shells will still be POSIX
                        # compliant--not true for some cases for LISA
                        # users.
                        func_type = type(
                            spur.ssh.ShellTypes.minimal.generate_run_command
                        )
                        self._inner_shell._spur._shell_type.generate_run_command = (
                            func_type(
                                minimal_generate_run_command,
                                self._inner_shell._spur._shell_type,
                            )
                        )
                else:
                    raise identifier
        return process

    def mkdir(
        self,
        path: PurePath,
        mode: int = 0o777,
        parents: bool = True,
        exist_ok: bool = False,
    ) -> None:
        """Create the directory(ies), if they do not already exist.
        Inputs:
            path: directory path. (Absolute. Use a PurePosixPath, if the
                                   target node is a Posix one, because LISA
                                   might be ran from Windows)
            mode: directory creation mode (Posix targets only)
            parents: make parent directories as needed
            exist_ok: return with no error if target already present
        """
        path_str = self._purepath_to_str(path)
        self.initialize()
        assert self._inner_shell
        try:
            self._inner_shell.mkdir(
                path_str, mode=mode, parents=parents, exist_ok=exist_ok
            )
        except PermissionError:
            self._inner_shell.run(command=["sudo", "mkdir", "-p", path_str])
        except SSHException as identifier:
            # no sftp, try commands
            if "Channel closed." in str(identifier):
                assert isinstance(path_str, str)
                self.spawn(command=["mkdir", "-p", path_str])
        except OSError as e:
            if not self.is_posix and parents:
                # spurplus doesn't handle Windows style paths properly. As a result,
                # it is unable to create parent directories when parents=True is
                # passed. So, mkdir ultimately fails. In such cases, use command
                # instead. On Windows, mkdir creates parent directories by default;
                # no additional parameter is needed.
                self._inner_shell.run(command=["mkdir", path_str])
            else:
                raise e

    def exists(self, path: PurePath) -> bool:
        """Check if a target directory/file exist
        Inputs:
            path: target path. (Absolute. Use a PurePosixPath, if the
                                target node is a Posix one, because LISA
                                might be ran from Windows)
        Outputs:
            bool: True if present, False otherwise
        """
        self.initialize()
        assert self._inner_shell
        path_str = self._purepath_to_str(path)
        return cast(bool, self._inner_shell.exists(path_str))

    def remove(self, path: PurePath, recursive: bool = False) -> None:
        """Remove a target directory/file
        Inputs:
            path: target path. (Absolute. Use a PurePosixPath, if the
                                target node is a Posix one, because LISA
                                might be ran from Windows)
            recursive: whether to remove recursively, if target is a directory
                       (will fail if that's the case and this flag is off)
        """
        self.initialize()
        assert self._inner_shell
        path_str = self._purepath_to_str(path)
        try:
            self._inner_shell.remove(path_str, recursive)
        except PermissionError:
            self._inner_shell.run(command=["sudo", "rm", path_str])
        except SSHException as identifier:
            # no sftp, try commands
            if "Channel closed." in str(identifier):
                assert isinstance(path_str, str)
                self.spawn(command=["rm", path_str])

    def chmod(self, path: PurePath, mode: int) -> None:
        """
        Change the file mode bits of each given file according to mode
        (Posix targets only)

        Inputs:
            path: target path. (Absolute. Use a PurePosixPath, if the
                                target node is a Posix one, because LISA
                                might be ran from Windows)
            mode: numerical chmod mode entry
        """
        self.initialize()
        assert self._inner_shell
        path_str = self._purepath_to_str(path)
        self._inner_shell.chmod(path_str, mode)

    def stat(self, path: PurePath) -> os.stat_result:
        """Display file/directory status.
        Inputs:
            path: target path. (Absolute. Use a PurePosixPath, if the
                                target node is a Posix one, because LISA
                                might be ran from Windows)
        Outputs:
            os.stat_result: The status structure/class
        """
        self.initialize()
        assert self._inner_shell
        path_str = self._purepath_to_str(path)
        sftp_attributes: paramiko.SFTPAttributes = self._inner_shell.stat(path_str)

        result = os.stat_result(
            (
                # st_mode
                sftp_attributes.st_mode if sftp_attributes.st_mode is not None else 0,
                # st_ino
                0,
                # st_dev
                0,
                # st_nlink
                0,
                # st_uid
                sftp_attributes.st_uid if sftp_attributes.st_uid is not None else 0,
                # st_gid
                sftp_attributes.st_gid if sftp_attributes.st_gid is not None else 0,
                # st_size
                sftp_attributes.st_size if sftp_attributes.st_size is not None else 0,
                # st_atime
                sftp_attributes.st_atime if sftp_attributes.st_atime is not None else 0,
                # st_mtime
                sftp_attributes.st_mtime if sftp_attributes.st_mtime is not None else 0,
                # st_ctime
                0,
            )
        )
        return result

    def is_dir(self, path: PurePath) -> bool:
        """Check if given path is a directory
        Inputs:
            path: target path. (Absolute. Use a PurePosixPath, if the
                                target node is a Posix one, because LISA
                                might be ran from Windows)
        Outputs:
            bool: True if it is a directory, False otherwise
        """
        self.initialize()
        assert self._inner_shell
        path_str = self._purepath_to_str(path)
        return cast(bool, self._inner_shell.is_dir(path_str))

    def is_symlink(self, path: PurePath) -> bool:
        """Check if given path is a symlink
        Inputs:
            path: target path. (Absolute. Use a PurePosixPath, if the
                                target node is a Posix one, because LISA
                                might be ran from Windows)
        Outputs:
            bool: True if it is a symlink, False otherwise
        """
        self.initialize()
        assert self._inner_shell
        path_str = self._purepath_to_str(path)
        return cast(bool, self._inner_shell.is_symlink(path_str))

    def symlink(self, source: PurePath, destination: PurePath) -> None:
        """Create a symbolic link from source to destination, in the target node
        Inputs:
            source: source path. (Absolute. Use a PurePosixPath, if the
                                 target node is a Posix one, because LISA
                                 might be ran from Windows)
            destination: destination path. (Absolute. Use a PurePosixPath, if the
                                            target node is a Posix one, because LISA
                                            might be ran from Windows)
        """
        self.initialize()
        assert self._inner_shell
        source_str = self._purepath_to_str(source)
        destination_str = self._purepath_to_str(destination)
        self._inner_shell.symlink(source_str, destination_str)

    def copy(self, local_path: PurePath, node_path: PurePath) -> None:
        """Upload local file to target node
        Inputs:
            local_path: local path. (Absolute. Use a PurePosixPath, if the
                                     target node is a Posix one, because LISA
                                     might be ran from Windows)
            node_path: target path. (Absolute. Use a PurePosixPath, if the
                                     target node is a Posix one, because LISA
                                     might be ran from Windows)
        """
        self.mkdir(node_path.parent, parents=True, exist_ok=True)
        self.initialize()
        assert self._inner_shell
        local_path_str = self._purepath_to_str(local_path, True)
        node_path_str = self._purepath_to_str(node_path, False)
        self._inner_shell.put(
            local_path_str,
            node_path_str,
            create_directories=True,
            consistent=self.is_posix,
        )

    def copy_back(self, node_path: PurePath, local_path: PurePath) -> None:
        """Download target node's file to local node
        Inputs:
            local_path: local path. (Absolute. Use a PurePosixPath, if the
                                     target node is a Posix one, because LISA
                                     might be ran from Windows)
            node_path: target path. (Absolute. Use a PurePosixPath, if the
                                     target node is a Posix one, because LISA
                                     might be ran from Windows)
        """
        self.initialize()
        assert self._inner_shell
        node_path_str = self._purepath_to_str(node_path, False)
        local_path_str = self._purepath_to_str(local_path, True)
        self._inner_shell.get(
            node_path_str,
            local_path_str,
            consistent=self.is_posix,
        )

    def _purepath_to_str(
        self, path: Union[Path, PurePath, str], is_local: bool = False
    ) -> Union[Path, PurePath, str]:
        """
        spurplus doesn't support pure path, so it needs to convert.
        """
        if isinstance(path, PurePath):
            if is_local:
                path = str(path)
            elif self.is_posix:
                path = path.as_posix()
            else:
                path = str(PureWindowsPath(path))
        return path

    def _establish_jump_boxes(self, address: str, port: int) -> Any:
        jump_boxes_runbook = development.get_jump_boxes()
        sock: Any = None
        is_trace_enabled = development.is_trace_enabled()
        if is_trace_enabled:
            jb_logger = _get_jump_box_logger()
            jb_logger.debug(f"proxy sock: {sock}")

        for index, runbook in enumerate(jump_boxes_runbook):
            if is_trace_enabled:
                jb_logger.debug(f"creating connection from source: {runbook} ")
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.MissingHostKeyPolicy())
            client.connect(
                hostname=runbook.address,
                port=runbook.port,
                username=runbook.username,
                password=runbook.password,
                key_filename=runbook.private_key_file,
                banner_timeout=10,
                sock=sock,
            )

            if index < len(jump_boxes_runbook) - 1:
                next_hop = jump_boxes_runbook[index + 1]
                dest_address = (
                    next_hop.private_address
                    if next_hop.private_address
                    else next_hop.address
                )
                dest_port = (
                    next_hop.private_port if next_hop.private_port else next_hop.port
                )
            else:
                dest_address = address
                dest_port = port

            if is_trace_enabled:
                jb_logger.debug(f"next hop: {dest_address}:{dest_port}")
            sock = self._open_jump_box_channel(
                client,
                src_address=runbook.address,
                src_port=runbook.port,
                dest_address=dest_address,
                dest_port=dest_port,
            )
            self._jump_boxes.append(client)

        return sock

    def _open_jump_box_channel(
        self,
        client: paramiko.SSHClient,
        src_address: str,
        src_port: int,
        dest_address: str,
        dest_port: int,
    ) -> Any:
        transport = client.get_transport()
        assert transport

        sock = transport.open_channel(
            kind="direct-tcpip",
            src_addr=(src_address, src_port),
            dest_addr=(dest_address, dest_port),
        )

        return sock

    def _close_jump_boxes(self) -> None:
        for index in reversed(range(len(self._jump_boxes))):
            self._jump_boxes[index].close()
            self._jump_boxes[index] = None

        self._jump_boxes.clear()
        self._jump_box_sock = None


class LocalShell(InitializableMixin):
    def __init__(self) -> None:
        super().__init__()
        self.is_remote = False
        self._inner_shell = spur.LocalShell()

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        if "win32" == sys.platform:
            self.is_posix = False
        else:
            self.is_posix = True

    def close(self) -> None:
        ...

    @property
    def is_connected(self) -> bool:
        # local shell is always available.
        return True

    def spawn(
        self,
        command: Sequence[str],
        update_env: Optional[Mapping[str, str]] = None,
        store_pid: bool = False,
        cwd: Optional[Union[str, Path]] = None,
        stdout: Any = None,
        stderr: Any = None,
        encoding: str = "utf-8",
        use_pty: bool = False,
        allow_error: bool = False,
    ) -> spur.local.LocalProcess:
        return self._inner_shell.spawn(
            command=command,
            update_env=update_env,
            store_pid=store_pid,
            cwd=cwd,
            stdout=stdout,
            stderr=stderr,
            encoding=encoding,
            use_pty=use_pty,
            allow_error=allow_error,
        )

    def mkdir(
        self,
        path: PurePath,
        mode: int = 0o777,
        parents: bool = True,
        exist_ok: bool = False,
    ) -> None:
        """Create the directory(ies), if they do not already exist.
        Inputs:
            path: directory path. (Absolute)
            mode: directory creation mode (Posix targets only)
            parents: make parent directories as needed
            exist_ok: return with no error if target already present
        """
        if not isinstance(path, Path):
            path = Path(path)
        path.mkdir(mode=mode, parents=parents, exist_ok=exist_ok)

    def exists(self, path: PurePath) -> bool:
        """Check if a target directory/file exist
        Inputs:
            path: target path. (Absolute)
        Outputs:
            bool: True if present, False otherwise
        """
        if not isinstance(path, Path):
            path = Path(path)
        return path.exists()

    def remove(self, path: PurePath, recursive: bool = False) -> None:
        """Remove a target directory/file
        Inputs:
            path: target path. (Absolute)
            recursive: whether to remove recursively, if target is a directory
                       (will fail if that's the case and this flag is off)
        """
        if not isinstance(path, Path):
            path = Path(path)
        if path.is_dir():
            if recursive:
                shutil.rmtree(path)
            else:
                path.rmdir()
        else:
            path.unlink()

    def chmod(self, path: PurePath, mode: int) -> None:
        """
        Change the file mode bits of each given file according to mode
        (Posix targets only)

        Inputs:
            path: target path. (Absolute)
            mode: numerical chmod mode entry
        """
        if not isinstance(path, Path):
            path = Path(path)
        path.chmod(mode)

    def stat(self, path: PurePath) -> os.stat_result:
        """Display file/directory status.
        Inputs:
            path: target path. (Absolute)
        Outputs:
            os.stat_result: The status structure/class
        """
        if not isinstance(path, Path):
            path = Path(path)
        return path.stat()

    def is_dir(self, path: PurePath) -> bool:
        """Check if given path is a directory
        Inputs:
            path: target path. (Absolute)
        Outputs:
            bool: True if it is a directory, False otherwise
        """
        if not isinstance(path, Path):
            path = Path(path)
        return path.is_dir()

    def is_symlink(self, path: PurePath) -> bool:
        """Check if given path is a symlink
        Inputs:
            path: target path. (Absolute)
        Outputs:
            bool: True if it is a symlink, False otherwise
        """
        if not isinstance(path, Path):
            path = Path(path)
        return path.is_symlink()

    def symlink(self, source: PurePath, destination: PurePath) -> None:
        """Create a symbolic link from source to destination, in the target node
        Inputs:
            source: source path. (Absolute)
            destination: destination path. (Absolute)
        """
        if not isinstance(source, Path):
            source = Path(source)
        if not isinstance(destination, Path):
            destination = Path(destination)
        source.symlink_to(destination)

    def copy(self, local_path: PurePath, node_path: PurePath) -> None:
        """Upload local file to target node
        Inputs:
            local_path: local path. (Absolute)
            node_path: target path. (Absolute)
        """
        self.mkdir(node_path.parent, parents=True, exist_ok=True)
        shutil.copy(local_path, node_path)

    def copy_back(self, node_path: PurePath, local_path: PurePath) -> None:
        """Download target node's file to local node
        Inputs:
            local_path: local path. (Absolute)
            node_path: target path. (Absolute)
        """
        self.copy(local_path=node_path, node_path=local_path)


class WslShell(InitializableMixin):
    def __init__(self, parent: "Shell", distro_name: str) -> None:
        super().__init__()
        self._parent = parent
        self._distro_name = distro_name

    def __getattr__(self, key: str) -> Any:
        return getattr(self._parent, key)

    def copy(self, local_path: PurePath, node_path: PurePath) -> None:
        """
        Copy to temp folder for transfer between WSL and Windows.
        """
        # parent must be Windows
        host_temp_file = self._get_parent_temp_path() / node_path.name

        self._parent.copy(local_path, host_temp_file)

        wsl_path = self._get_wsl_file_windows_path(node_path)
        process = self._parent.spawn(
            command=["cmd", "/c", "copy", "/y", str(host_temp_file), str(wsl_path)]
        )
        self._wait_process_output(process)

        self._parent.remove(host_temp_file)

    def copy_back(self, node_path: PurePath, local_path: PurePath) -> None:
        """
        Copy to temp folder for transfer between WSL and Windows.
        """
        host_temp_file = self._get_parent_temp_path() / node_path.name
        wsl_path = self._get_wsl_file_windows_path(node_path)
        process = self._parent.spawn(
            command=["cmd", "/c", "copy", "/y", str(wsl_path), str(host_temp_file)]
        )
        self._wait_process_output(process)

        try:
            self._parent.copy_back(host_temp_file, local_path)
        except Exception as e:
            raise LisaException(
                f"failed to copy back {node_path} to {local_path}. "
                f"temp path: {host_temp_file}. error: {e}"
            )

        self._parent.remove(host_temp_file)

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        return self._parent._initialize(*args, **kwargs)

    def _get_parent_temp_path(self) -> PureWindowsPath:
        process = self._parent.spawn(["cmd", "/c", "echo %TEMP%"])

        return PureWindowsPath(self._wait_process_output(process))

    def _get_wsl_file_windows_path(self, wsl_path: PurePath) -> PureWindowsPath:
        return PureWindowsPath(rf"\\wsl$\{self._distro_name}") / wsl_path

    def _wait_process_output(self, process: Any) -> str:
        result = process.wait_for_result()
        result.output = filter_ansi_escape(result.output)

        if isinstance(self._parent, SshShell):
            # remove extra line in Windows SSH shell.
            result.output = "\n".join(result.output.split("\n")[:-1])

        return str(result.output.strip())


Shell = Union[LocalShell, SshShell, WslShell]
