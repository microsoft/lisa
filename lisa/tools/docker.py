# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from retry import retry

from lisa.base_tools import Service, Wget
from lisa.executable import Tool
from lisa.operating_system import BSD, CBLMariner, CentOs, Debian, Fedora, Redhat, Suse
from lisa.util import (
    LisaException,
    ReleaseEndOfLifeException,
    RepoNotExistException,
    UnsupportedDistroException,
)


class Docker(Tool):
    @property
    def command(self) -> str:
        return "docker"

    @property
    def can_install(self) -> bool:
        return True

    @retry(tries=10, delay=5)  # type: ignore
    def build_image(self, image_name: str, dockerfile: str) -> None:
        # alpine image build need to specify '--network host'
        self.run(
            f"build -t {image_name} -f {dockerfile} . --network host",
            shell=True,
            sudo=True,
            cwd=self.node.working_path,
            force_run=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="Docker image build failed.",
        )

    # Executes command inside of container
    def exec_command(self, container_name: str, command: str) -> str:
        return self.run(f"exec {container_name} {command}", sudo=True).stdout

    def remove_container(self, container_name: str) -> None:
        self._log.debug(f"Removing Docker Container {container_name}")
        self.run(f"rm {container_name}", sudo=True, force_run=True)

    def remove_image(self, image_name: str) -> None:
        self._log.debug(f"Removing Docker Image {image_name}")
        self.run(f"rmi {image_name}", sudo=True, force_run=True)

    def run_container(
        self,
        image_name: str,
        container_name: str,
        docker_run_output: str,
    ) -> None:
        self.run(
            f"run --name {container_name} {image_name} > {docker_run_output} 2>&1",
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
        # for rhel 8, the service name may be podman (newer podman package)
        # may be io.podman.socket (older podman package)
        # remain ones use docker service
        # once detect one existing service, enable and restart it, then exit the loop
        for service_name in ["docker", "podman", "io.podman.socket"]:
            if service.check_service_exists(service_name):
                service.enable_service(service_name)
                service.restart_service(service_name)
                break

    def _check_exists(self) -> bool:
        if super()._check_exists():
            self.start()
        return super()._check_exists()

    def _install(self) -> bool:
        if isinstance(self.node.os, Debian):
            try:
                self.node.os.install_packages("docker.io")
            except (RepoNotExistException, ReleaseEndOfLifeException) as e:
                raise e
            except Exception as e:
                self._log.error(
                    f"Failed to install docker.io: {e}, trying to install docker from"
                    " repo"
                )
                self._install_from_repo()
        elif (
            isinstance(self.node.os, CentOs)
            and self.node.os.information.release >= "8.0"
        ):
            wget_tool = self.node.tools[Wget]
            wget_tool.get(
                "https://get.docker.com",
                filename="get-docker.sh",
                file_path="./",
                executable=True,
            )
            self.node.execute("./get-docker.sh", sudo=True)
        # RHEL 8 and its derivatives don't support docker
        elif isinstance(self.node.os, Redhat):
            if self.node.os.information.version >= "8.0.0":
                # disable SELinux to avoid issue
                # error while loading shared libraries: libc.so.6:
                # cannot change memory protections
                self.node.execute("setenforce 0", sudo=True)
                self.node.os.install_packages("podman")
                self.node.execute(
                    "ln -s /run/podman/podman.sock /var/run/docker.sock",
                    sudo=True,
                    shell=True,
                )
                self.node.execute(
                    "ln -s /bin/podman /bin/docker", sudo=True, shell=True
                )
            else:
                self.node.os.add_repository(
                    repo="https://download.docker.com/linux/centos/docker-ce.repo",
                    repo_name="docker-ce.repo",
                )
                self.node.os.add_repository(
                    repo="https://vault.centos.org/centos/7/extras/x86_64",
                    repo_name="Centos extras",
                )
                self.node.os.add_repository(
                    repo="https://vault.centos.org/centos/7/os/x86_64",
                    repo_name="Centos extras",
                )
                gpg_donwload_path = self.node.tools[Wget].get(
                    "https://vault.centos.org/centos/7/os/x86_64/RPM-GPG-KEY-CentOS-7",
                )
                self.node.execute(f"rpm --import {gpg_donwload_path}", sudo=True)

                self.node.os.install_packages(
                    ["docker-ce", "docker-ce-cli", "containerd.io"]
                )
        elif isinstance(self.node.os, CBLMariner):
            self.node.os.install_packages(["moby-engine", "moby-cli"])
        elif isinstance(self.node.os, Suse) or isinstance(self.node.os, Fedora):
            self.node.os.install_packages(["docker"])
        elif isinstance(self.node.os, BSD):
            raise UnsupportedDistroException(
                self.node.os,
                "Docker is not supported to run natively on BSD. "
                "Please check the supported distros here: "
                "https://docs.docker.com/engine/install",
            )
        else:
            raise LisaException(f"{self.node.os.information.vendor} not supported")
        self.start()
        return self._check_exists()

    def _install_from_repo(self) -> None:
        if isinstance(self.node.os, Debian):
            self.node.os.install_packages(
                [
                    "apt-transport-https",
                    "ca-certificates",
                    "curl",
                    "gnupg2",
                    "software-properties-common",
                ]
            )
            self.node.execute(
                "curl -fsSL https://download.docker.com/linux/debian/gpg | sudo apt-key"
                " add -",
                shell=True,
                sudo=True,
            )
            lsb_release_code = self.node.os.information.codename
            self.node.os.add_repository(
                repo=(
                    "deb [arch=amd64] https://download.docker.com/linux/debian"
                    f" {lsb_release_code} stable"
                ),
            )
            self.node.execute("apt update", sudo=True, shell=True)
            self.node.os.install_packages("docker-ce")
        else:
            raise LisaException(
                f"{self.node.os.information.vendor} not supported for install from repo"
            )
