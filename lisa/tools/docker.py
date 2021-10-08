# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from lisa.executable import Tool
from lisa.operating_system import Debian, Redhat
from lisa.tools.service import Service
from lisa.util import LisaException


class Docker(Tool):
    @property
    def command(self) -> str:
        return "docker"

    @property
    def can_install(self) -> bool:
        return True

    def build_image(
        self, docker_image_name: str = "testing", dockerfile: str = "Dockerfile"
    ) -> None:
        self.run(
            f"build -t {docker_image_name} -f {dockerfile} .",
            shell=True,
            sudo=True,
            cwd=self.node.working_path,
            force_run=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="Docker image build failed.",
        )

    def remove_container(self, container_name: str) -> None:
        self._log.debug(f"Removing Docker Container {container_name}")
        self.run(f"rm {container_name}", sudo=True, force_run=True)

    def remove_image(self, image_name: str) -> None:
        self._log.debug(f"Removing Docker Image {image_name}")
        self.run(f"rmi {image_name}", sudo=True, force_run=True)

    def run_container(
        self,
        docker_image_name: str,
        docker_container_name: str,
        docker_run_output: str,
    ) -> None:
        self.run(
            f"run --name {docker_container_name} "
            f"{docker_image_name} 1> {docker_run_output} 2>&1",
            shell=True,
            sudo=True,
            cwd=self.node.working_path,
            force_run=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="Docker run failed.",
        )

    def start(self) -> None:
        self._log.debug("Start docker engine")
        service = self.node.tools[Service]
        service.enable_service("docker")
        service.restart_service("docker")

    def _install(self) -> bool:
        if isinstance(self.node.os, Debian):
            self.node.os.install_packages("docker.io")
        elif isinstance(self.node.os, Redhat):
            self.node.os.install_packages(
                ["docker", "docker-ce", "docker.socket", "docker.service"]
            )
        else:
            raise LisaException(f"{self.node.os.information.vendor} not supported")

        self.start()
        return True
