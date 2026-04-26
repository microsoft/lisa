# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from pathlib import PurePath

from lisa.base_tools import Service, Uname, Wget
from lisa.executable import Tool
from lisa.operating_system import Posix, Redhat
from lisa.util import LisaException, get_matched_str


class DockerCompose(Tool):
    # Error response from daemon: crun: /usr/bin/crun: symbol lookup error:
    #  /usr/bin/crun: undefined symbol: criu_feature_check: OCI runtime error
    ERROR_PATTERN = re.compile(
        r"Error response from daemon: crun:.*symbol lookup error.*"
        r"undefined symbol: criu_feature_check",
        re.M,
    )

    _compose_command: str = ""

    @property
    def command(self) -> str:
        return self._compose_command or "docker compose"

    @property
    def can_install(self) -> bool:
        return True

    def _check_exists(self) -> bool:
        # Prefer "docker compose" (v2 CLI plugin) — its API version matches
        # the installed Docker Engine, avoiding client/daemon mismatches
        # like "client version 1.42 is too old. Minimum supported API
        # version is 1.44".
        result = self.node.execute(
            "docker compose version", shell=True, no_info_log=True
        )
        if result.exit_code == 0:
            self._compose_command = "docker compose"
            return True
        # Fall back to standalone "docker-compose" binary.
        exists, self._use_sudo = self.command_exists("docker-compose")
        if exists:
            self._compose_command = "docker-compose"
            return True
        return False

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
        result.assert_exit_code(message=f"fail to launch {self.command} up -d")

    def _install_from_source(self) -> None:
        wget_tool = self.node.tools[Wget]
        uname_tool = self.node.tools[Uname]
        hardware = uname_tool.get_linux_information().hardware_platform
        # Install as a Docker CLI plugin so it is accessible via
        # "docker compose" and uses the correct Docker API version.
        plugin_dir = "/usr/libexec/docker/cli-plugins"
        self.node.execute(f"mkdir -p {plugin_dir}", sudo=True)
        target = f"{plugin_dir}/docker-compose"
        wget_tool.run(
            "https://github.com/docker/compose/releases/download/v2.29.2"
            f"/docker-compose-linux-{hardware} -O {target}",
            sudo=True,
        )
        self.node.execute(f"chmod +x {target}", sudo=True)

    def _install(self) -> bool:
        if isinstance(self.node.os, Posix):
            # Try the docker-compose-plugin distro package first (available
            # when Docker's official apt/yum repo is configured), then fall
            # back to downloading the binary.
            try:
                self.node.os.install_packages("docker-compose-plugin")
                if self._check_exists():
                    return True
            except Exception as e:
                self._log.debug(
                    f"docker-compose-plugin package unavailable ({e}), "
                    "installing from source"
                )
            self._install_from_source()
        else:
            raise LisaException(f"Not supported on {self.node.os.information.vendor}")
        return self._check_exists()
