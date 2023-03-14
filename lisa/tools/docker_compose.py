# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from pathlib import PurePath

from lisa.base_tools import Mv, Service, Uname, Wget
from lisa.executable import Tool
from lisa.operating_system import CBLMariner, Posix, Redhat
from lisa.util import LisaException, get_matched_str


class DockerCompose(Tool):
    # Error response from daemon: crun: /usr/bin/crun: symbol lookup error:
    #  /usr/bin/crun: undefined symbol: criu_feature_check: OCI runtime error
    ERROR_PATTERN = re.compile(
        r"Error response from daemon: crun:.*symbol lookup error.*"
        r"undefined symbol: criu_feature_check",
        re.M,
    )

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
        result = self.run("up -d", sudo=True, cwd=path)
        # temp solution, will revert change once newer package
        # which can fix the issue release
        # refer https://access.redhat.com/discussions/6988326
        if result.exit_code != 0 and get_matched_str(result.stdout, self.ERROR_PATTERN):
            if (
                isinstance(self.node.os, Redhat)
                and self.node.os.information.version >= "9.0.0"
            ):
                self.node.os.install_packages("crun-1.4.5-2*")
                result = self.run("up -d", sudo=True, cwd=path, force_run=True)
        result.assert_exit_code(message="fail to launch docker-compose up -d")

    def _install_from_source(self) -> None:
        wget_tool = self.node.tools[Wget]
        uname_tool = self.node.tools[Uname]
        hardware = uname_tool.get_linux_information().hardware_platform
        filename = "docker-compose"
        wget_tool.run(
            "https://github.com/docker/compose/releases/download/v2.14.2"
            f"/docker-compose-Linux-{hardware} -O {filename}",
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
