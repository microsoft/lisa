# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import PurePath

from lisa.base_tools import Mv, Service, Uname, Wget
from lisa.executable import Tool
from lisa.operating_system import CBLMariner, Posix, Redhat
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
        self.run(
            "up -d",
            sudo=True,
            cwd=path,
            expected_exit_code=0,
            expected_exit_code_failure_message="fail to launch docker-compose up -d",
        )

    def _install_from_source(self) -> None:
        wget_tool = self.node.tools[Wget]
        uname_tool = self.node.tools[Uname]
        hardware = uname_tool.get_linux_information().hardware_platform
        filename = "docker-compose"
        wget_tool.run(
            "https://github.com/docker/compose/releases/download/v2.0.1"
            f"/docker-compose-linux-{hardware} -O {filename}",
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                f"fail to download docker-compose-linux-{hardware}"
            ),
            sudo=True,
        )
        self.node.execute(f"sudo chmod +x {filename}")
        self.node.tools[Mv].move(
            "docker-compose", "/usr/bin/", overwrite=True, sudo=True
        )

    def _install(self) -> bool:
        # The default installed docker-compose package doesn't work for
        # redhat so it uses the latest version
        if isinstance(self.node.os, Redhat) or isinstance(self.node.os, CBLMariner):
            self._install_from_source()
        elif isinstance(self.node.os, Posix):
            try:
                self._install_from_source()
            except Exception as e:
                self._log.info(
                    f"Failed to install docker-compose from source. Error: {e}"
                )
                self.node.os.install_packages("docker-compose")
        else:
            raise LisaException(f"Not supported on {self.node.os.information.vendor}")
        return self._check_exists()
