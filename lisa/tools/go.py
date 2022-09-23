# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Any, List, Type

from lisa.base_tools.wget import Wget
from lisa.executable import Tool
from lisa.operating_system import Posix
from lisa.tools.echo import Echo
from lisa.tools.rm import Rm
from lisa.tools.tar import Tar
from lisa.util import LisaException


class Go(Tool):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        go_version = kwargs.pop("go_version", None)
        if go_version:
            self._install_specific_version(go_version)

    @property
    def command(self) -> str:
        return "go"

    @property
    def can_install(self) -> bool:
        return True

    @property
    def dependencies(self) -> List[Type[Tool]]:
        return [Wget, Tar, Rm]

    def _install(self) -> bool:
        if isinstance(self.node.os, Posix):
            self.node.os.install_packages("golang-go")
        else:
            raise LisaException(
                "Doesn't support to install Go in Windows. "
                "Make sure Go is installed and in PATH"
            )
        return self._check_exists()

    def _install_specific_version(self, version: str) -> bool:
        version_list = []
        version_list.append("1.15")
        version_list += [f"1.15.{i}" for i in range(1, 16)]
        version_list.append("1.16")
        version_list += [f"1.16.{i}" for i in range(1, 16)]
        version_list.append("1.17")
        version_list += [f"1.17.{i}" for i in range(1, 14)]
        version_list.append("1.18")
        version_list += [f"1.18.{i}" for i in range(1, 17)]
        version_list.append("1.19")
        version_list += [f"1.19.{i}" for i in range(1, 2)]
        url: str = ""

        if version not in version_list:
            raise LisaException(
                f"Version {version} not supported , \
                    supported Versions are : {version_list}"
            )
        else:
            url = f"https://dl.google.com/go/go{version}.linux-amd64.tar.gz"

        tool_path = self.node.get_working_path()

        # Get GoLang Source file
        wget = self.node.tools[Wget]
        download_path = wget.get(url, file_path=tool_path.as_posix(), overwrite=True)

        # Extract tar with gzip as true
        tar = self.node.tools[Tar]
        tar.extract(file=download_path, dest_dir="/usr/local", sudo=True, gzip=True)

        # Add installation path to env variable PATH
        echo = self.node.tools[Echo]
        original_path = echo.run(
            "$PATH",
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="failure to grab $PATH via echo",
        ).stdout
        new_path = f"/usr/local/go/bin/:{original_path}"
        self._log.debug("NewPath : " + str(new_path))
        self.node.execute(
            "go version",
            cwd=tool_path,
            update_envs={"PATH": new_path},
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "Could not install go modules for nff-go"
            ),
        )

        # Remove the tar file
        rm = self.node.tools[Rm]
        rm.remove_file(download_path)

        return self._check_exists()

    def get_version(self) -> str:
        op = self.node.execute("go version")
        return op.stdout if op.stdout else "GoLang is not installed"
