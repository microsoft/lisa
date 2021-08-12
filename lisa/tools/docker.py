# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import lisa
from lisa.util import LisaException
from typing import final

from lisa import SkippedException
from lisa.base_tools import Wget
from lisa.executable import Tool
from lisa.operating_system import CentOs, Debian, Posix, Redhat, Ubuntu

DOCKER_BUILD_OUTPUT : str = "docker_build.log"
DOCKER_RUN_OUTPUT : str = "docker_run.log"

class Docker(Tool):

    @property
    def command(self) -> str:
        return "docker"

    @property
    def can_install(self) -> bool:
        return True

    def _install(self) -> None:
        #final_exit_code = 2
        self._log.debug("Installing Docker Engine on {self.node.os}}")

        ### UPDATE UTILS NOT NEEDED
        package_list = ["docker-ce-cli", "containerd.io", "docker-ce"]

        # Couldnt find Mariner, almalinux, or rockylinux in operating_system.py
        if isinstance(self.node.os, Debian) or isinstance(self.node.os, Ubuntu):
            self._log.debug(
                "Install packages apt-transport-https ca-certificates curl gnupg-agent"
                " software-properties-common."
            )
            self.node.os.install_packages("apt-transport-https ca-certificates curl "
            "gnupg-agent software-properties-common"
            )

            self._log.debug("Add Docker's official GPG key.")
            #curl -fsSL https://download.docker.com/linux/$DISTRO_NAME/gpg | sudo apt-key add -
            wget_tool = self.node.tools[Wget]
            wget_tool.get(
                url=f"https://download.docker.com/linux/"
                f"{self.node.os._information.vendor.lower()}/gpg",
                file_path="wget",
                filename="gpg",
            )
            self.node.execute(cmd="apt-key add wget/gpg",shell=True, sudo=True)

            self._log.debug("Set up the stable repository.")

            #release=$(lsb_release -cs)
            release = self.node.execute(cmd="lsb_release -cs").__str__()

            self.node.execute(
                f"add-apt-repository -y \"deb https://download.docker.com/linux/"
                f"{self.node.os.information.vendor.lower()} ${release} stable\""
            )

            if self.node.os.information.release == "14.04":
                package_list = ["docker-ce"]

            self.node.os.install_packages(package_list) # package_list
            """if isinstance(self.node.os, Posix):
                self.node.os.install_packages([self])"""

            """
            for package in package_list:
                exit_code = self.node.execute(f"check_package \"{package}\"").exit_code
                if exit_code == 0: 
                    final_exit_code = self.node.execute(f"install_package \"{package}\"").exit_code
            """

        elif isinstance(self.node.os, Redhat) or isinstance(self.node.os, CentOs):

            self._log.debug("Install package yum-utils.")
            self.node.execute("install_package \"yum-utils\"")

            docker_url = "https://download.docker.com/linux/centos/docker-ce.repo"
            self._log.debug(f"Add repo {docker_url}.")
            self.node.execute(f"yum-config-manager --add-repo {docker_url}")

            if self.node.os.information.version.major == 8:
                self.node.execute(
                    "sed -i -e 's/$releasever/8/g' /etc/yum.repos.d/docker-ce.repo"
                )
                self.node.execute(
                    "yum install --nogpgcheck -y docker-ce docker-ce-cli "
                    "containerd.io --nobest --allowerasing"
                )
            elif self.node.os.information.version.major == 7:
                self.node.execute(
                    "yum install -y http://mirror.centos.org/centos/7/extras/x86_64"
                    "/Packages/container-selinux-2.107-1.el7_6.noarch.rpm"
                )
                self.node.os.install_packages(package_list)
                """if isinstance(self.node.os, Posix):
                    self.node.os.install_packages(package_list)"""
                """for package in package_list:
                    exit_code = self.node.execute(f"check_package \"{package}\"").exit_code
                    if exit_code == 0: 
                        final_exit_code = self.node.execute(f"install_package \"{package}\"").exit_code"""
            else:
                #skipped test case 
                # HandleSkip "Test not supported for RH/CentOS $DISTRO_VERSION" $ret
                raise SkippedException("Test not supported for RH/CentOS $DISTRO_VERSION")
        else: 
            # HandleSkip "$DISTRO not supported" $ret
            raise SkippedException(f"{self.node.os.information.vendor} not supported")

        self._start_docker_engine()
        self._verify_docker_engine()
        """if not final_exit_code == 0:
            return final_exit_code #error

        final_exit_code = self._start_docker_engine()
        if not final_exit_code == 0:
            return final_exit_code #error

        final_exit_code = self._verify_docker_engine()
        #this isn't really necessary because from this point final exit code will be returned no matter what
        if not final_exit_code == 0:
            return final_exit_code #error

        return final_exit_code"""


    def _start_docker_engine(self) -> None:
        self._log.debug("Start docker engine")
        exit_code = self.node.execute(
            "systemctl start docker || service docker start"
        ).exit_code
        if not exit_code == 0:
            raise LisaException("Failed to start docker service")
            # self._log("Failed to start docker service") #error
            # return exit_code
        #return exit_code


    def _verify_docker_engine(self) -> None:
        self._log.debug("VerifyDockerEngine on $DISTRO")
        result = self.node.execute("docker run hello-world")
        if not result.exit_code == 0:
            raise LisaException("Fail to run docker run hello-world")
            # self._log("Fail to run docker run hello-world") #error
            # return result.exit_code

        self._log.debug(f"VerifyDockerEngine: hello-world output - {result.stdout}")
        # return result.exit_code


    """
    # Function to remove docker container
    function RemoveDockerContainer() {
        [[ -z "$1" ]] && {
            LogErr "RemoveDockerContainer: Docker container name / id missing."
            return 1
        } || local container_name="$1"

        docker rm $container_name
    }

    # Function to remove docker image
    function RemoveDockerImage() {
        [[ -z "$1" ]] && {
            LogErr "RemoveDockerImage: Docker container image name / id missing."
            return 1
        } || local container_img_name="$1"

        docker rmi $container_img_name
    }
    """
    def _remove_docker_container(self, container_name : str):
        pass

    def _remove_docker_image(self, image_name: str):
        pass

    def _build_docker_image(
        self, docker_image_name : str = "testing", dockerfile : str = "Dockerfile"
    ) -> None:
        exit_code = self.node.execute(
            f"docker build -t {docker_image_name} -f {dockerfile} "
            f". 1> {DOCKER_BUILD_OUTPUT} 2>&1" 
        ).exit_code
        if not exit_code == 0:
            raise LisaException(f"docker image build failed: {DOCKER_BUILD_OUTPUT}")
            # self._log(f"docker image build failed: {DOCKER_BUILD_OUTPUT}") #error
            # return exit_code
        self._log.debug("DOCKER BUILD OUTPUT:\n") 
        self._log.debug(self.node.execute(f"cat {DOCKER_BUILD_OUTPUT}").stdout)


    def _run_docker_container(
        self, docker_image_name : str, container_name : str = "testcon"
    ) -> None:
        exit_code = self.node.execute(
            f"docker run --name {container_name} "
            f"{docker_image_name} 1> {DOCKER_RUN_OUTPUT} 2>&1"
        )
        if not exit_code == 0:
            raise LisaException(f"docker run failed: {DOCKER_RUN_OUTPUT}.")
            # self._log(f"docker run failed: {DOCKER_RUN_OUTPUT}.") #error
            # return exit_code
        self._log.debug("DOCKER RUN OUTPUT:\n") 
        self._log.debug(self.node.execute(f"cat {DOCKER_RUN_OUTPUT}").stdout)
