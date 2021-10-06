# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import os
from pathlib import Path

from assertpy import assert_that

from lisa import Node, TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.operating_system import Redhat
from lisa.tools import Docker
from lisa.util import SkippedException


@TestSuiteMetadata(
    area="docker",
    category="functional",
    description="""
    This test suite runs the docker test cases for java, python, dotnet 3.1
    , dotnet5.0, and wordpress.
    """,
)
class docker(TestSuite):  # noqa
    @TestCaseMetadata(
        description="""
            This test case creates and runs a dotnet app using docker

            Steps:
            1. Install Dotnet 3.1 sdk
            2. Install Docker
            3. Copy dotnet dockerfile into node
            4. Create docker image and run docker container
            5. Check results of docker run against dotnet string identifier
        """,
        priority=2,
    )
    def docker_dotnet31_app(self, node: Node) -> None:
        dockerfile = "dotnet31.Dockerfile"

        self._execute_docker_test(
            node, "dotnetimage", "dotnetapp", "Hello World!", "", dockerfile
        )

    @TestCaseMetadata(
        description="""
            This test case creates and runs a dotnet app using docker

            Steps:
            1. Install Dotnet 5.0 sdk
            2. Install Docker
            3. Copy dotnet dockerfile into node
            4. Create docker image and run docker container
            5. Check results of docker run against dotnet string identifier
        """,
        priority=2,
    )
    def docker_dotnet50_app(self, node: Node) -> None:
        dockerfile = "dotnet50.Dockerfile"

        self._execute_docker_test(
            node, "dotnetimage", "dotnetapp", "Hello World!", "", dockerfile
        )

    @TestCaseMetadata(
        description="""
            This test case creates and runs a java app using docker

            Steps:
            1. Install Docker
            2. Copy java dockerfile and program file to node
            3. Create docker image and run docker container
            4. Check results of docker run against java string identifier
    """,
        priority=1,
    )
    def docker_java_app(self, node: Node) -> None:
        self._execute_docker_test(
            node,
            "javaappimage",
            "javaapp",
            "Hello world from java",
            "Main.java",
            "java.Dockerfile",
        )

    @TestCaseMetadata(
        description="""
            This test case creates and runs a python app using docker

            Steps:
            1. Install Docker
            2. Copy python dockerfile and program file to node
            3. Create docker image and run docker container
            4. Check results of docker run against python string identifier
        """,
        priority=3,
    )
    def docker_python_app(self, node: Node) -> None:
        self._execute_docker_test(
            node,
            "pythonappimage",
            "pythonapp",
            "Hello world from python",
            "helloworld.py",
            "python.Dockerfile",
        )

    def _copy_to_node(self, node: Node, filename: str) -> None:
        file_path = Path(os.path.dirname(__file__)) / "TestScripts" / filename
        if not node.shell.exists(node.working_path / filename):
            node.shell.copy(file_path, node.working_path / filename)

    def _execute_docker_test(
        self,
        node: Node,
        docker_image_name: str,
        docker_container_name: str,
        string_identifier: str,
        prog_src: str,
        dockerfile: str,
    ) -> None:
        docker_tool = self._verify_and_remove_containers(
            node, docker_image_name, docker_container_name
        )
        if prog_src:
            self._copy_to_node(node, prog_src)
        self._copy_to_node(node, dockerfile)
        self._run_and_verify_results(
            node,
            docker_tool,
            dockerfile,
            docker_image_name,
            docker_container_name,
            string_identifier,
        )

    def _run_and_verify_results(
        self,
        node: Node,
        docker_tool: Docker,
        dockerfile_name: str,
        docker_image_name: str,
        docker_container_name: str,
        string_identifier: str,
    ) -> None:
        docker_run_output_file = "docker_run.log"

        docker_tool.build_image(docker_image_name, dockerfile_name)
        docker_tool.run_container(
            docker_image_name, docker_container_name, docker_run_output_file
        )

        docker_tool.remove_image(docker_image_name)
        docker_tool.remove_container(docker_container_name)

        docker_run_output = node.execute(
            f"cat {docker_run_output_file}",
            expected_exit_code=0,
            expected_exit_code_failure_message="Docker run output file not found",
            cwd=node.working_path,
        ).stdout
        assert_that(docker_run_output).described_as(
            "The container didn't output expected result. "
            "There may have been errors when the container was run. "
            f"String Identifier: {string_identifier}. "
            f"Docker Run Output: {docker_run_output}."
        ).is_equal_to(string_identifier)

    def _skip_if_not_supported(self, node: Node) -> None:
        if isinstance(node.os, Redhat) and node.os.information.version < "7.0.0":
            raise SkippedException(
                f"Test not supported for RH/CentOS {node.os.information.release}"
            )

    def _verify_and_remove_containers(
        self, node: Node, docker_image_name: str, docker_container_name: str
    ) -> Docker:
        self._skip_if_not_supported(node)
        docker_tool = node.tools[Docker]
        self._verify_docker_engine(node)
        docker_tool.remove_image(docker_image_name)
        docker_tool.remove_container(docker_container_name)
        return docker_tool

    def _verify_docker_engine(self, node: Node) -> None:
        node.log.debug(f"VerifyDockerEngine on {node.os.information.vendor.lower()}")
        result = node.execute(
            "docker run hello-world",
            expected_exit_code=0,
            expected_exit_code_failure_message="Fail to run docker run hello-world",
            sudo=True,
        )
        node.log.debug(f"VerifyDockerEngine: hello-world output - {result.stdout}")
