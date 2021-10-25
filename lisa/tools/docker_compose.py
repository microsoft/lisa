# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import PurePath

from lisa.base_tools import Uname, Wget
from lisa.executable import Tool
from lisa.operating_system import Posix, Redhat
from lisa.tools.service import Service
from lisa.util import LisaException


class DockerCompose(Tool):
    @property
    def command(self) -> str:
        return "docker-compose"

    @property
    def can_install(self) -> bool:
        return True

    def start(self) -> None:
        self._log.debug("Start docker compose")
        service = self.node.tools[Service]
        service.enable_service("docker-compose")
        service.restart_service("docker-compose")

    def up(self, path: PurePath) -> None:
        self.run("up -d", sudo=True, cwd=path)

    def _install(self) -> bool:
        # The default installed docker-compose package doesn't work for
        # redhat so it uses the latest version
        if isinstance(self.node.os, Redhat):
            wget_tool = self.node.tools[Wget]
            uname_tool = self.node.tools[Uname]
            hardware = uname_tool.get_linux_information().hardware_platform
            filename = "docker-compose"
            wget_tool.run(
                "https://github.com/docker/compose/releases/download/1.23.2"
                f"/docker-compose-Linux-{hardware} -O {filename}",
                sudo=True,
            )
            self.node.execute(f"sudo chmod +x {filename}")
            self.node.execute(
                "mv docker-compose /usr/bin/", sudo=True, expected_exit_code=0
            )
        elif isinstance(self.node.os, Posix):
            self.node.os.install_packages("docker-compose")
        else:
            raise LisaException(f"Not supported on {self.node.os.information.vendor}")
        return self._check_exists()
