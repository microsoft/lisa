# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import TYPE_CHECKING
from typing import List, Type
from lisa.executable import Tool
from lisa.tools import Wget, Tar, Rm, Echo
from lisa.util import LisaException
from lisa.operating_system import Posix, Suse


if TYPE_CHECKING:
    from lisa.node import Node


class Go(Tool):
    def __init__(self, node: "Node") -> None:
        super().__init__(node)
        self._thread_count = 0

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
        if isinstance(self.node.os, Suse):
            self.node.os.install_packages("golang-go")
        elif isinstance(self.node.os, Posix):
            self.node.os.install_packages('golang-go')
        else:
            raise LisaException(
                "Doesn't support to install Go in Windows. "
                "Make sure Go is installed and in PATH"
            )
        return self._check_exists()

    def install_specific_version(self, version: str) -> bool:
        version_map = {
            "1.19" : {
                "url": "https://dl.google.com/go/go1.19.linux-amd64.tar.gz",
                "filename": "go1.19.linux-amd64.tar.gz"
            }
        }
        url: str = ""
        supported_version_csv: str = ",".join([i for i in version_map.keys()])

        if (version not in version_map.keys()):
            raise LisaException(
                f"Version {version} not supported , \
                    supported Versions are : {supported_version_csv}"
            )
        else:
            url = version_map[version]["url"]

        tool_path = self.get_tool_path(use_global=True)

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
