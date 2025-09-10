# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import os
import re
from pathlib import Path

from assertpy import assert_that

from lisa import (
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.operating_system import BSD, CentOs, Redhat, Windows
from lisa.tools import Docker, DockerCompose
from lisa.util import SkippedException, UnsupportedDistroException, get_matched_str


@TestSuiteMetadata(
    area="docker",
    category="functional",
    name="Docker",
    description="""
    This test suite runs the docker test cases for java, python, dotnet 3.1
    , dotnet5.0, and wordpress.
    """,
)
class DockerTestSuite(TestSuite):
    # Error: OCI runtime error: crun: /usr/bin/crun:
    # symbol lookup error: /usr/bin/crun: undefined symbol: criu_feature_check
    RHEL_ERROR_PATTERN = re.compile(
        r"Error: OCI runtime error: crun:.*symbol lookup error.*"
        r"undefined symbol: criu_feature_check",
        re.M,
    )
    CENTOS_ERROR_PATTERN = re.compile(
        r"OCI runtime create failed: unable to retrieve OCI runtime error", re.M
    )

    @TestCaseMetadata(
        description="""
            This test case uses docker-compose to create and run a wordpress mysql app

            Steps:
            1. Install Docker and Docker-Compose on node
            2. Copy docker-compose.yml into node
            3. Start docker container with docker-compose
            4. Run ps in the docker container and capture output
            5. Check that "apache2" can be found in captured output
        """,
        priority=3,
    )
    def verify_docker_compose_wordpress_app(self, node: Node) -> None:
        docker_tool = node.tools[Docker]
        docker_compose = node.tools[DockerCompose]

        self._copy_to_node(node, "docker-compose.yml")
        docker_compose.up(node.working_path)
        result = docker_tool.exec_command("wordpress_ex", "ps ax")
        identifier = "apache2"

        docker_tool.remove_image("wordpress mysql")
        docker_tool.remove_container("wordpress_ex")

        assert_that(result).described_as(
            "Docker exec didn't output the expected result which means that"
            " the wordpress app may not have been running as expected. "
            "There may have been errors when the container was run. "
            f"Docker exec output: {result}. "
            f"Expected Docker output to contain {identifier}"
        ).contains(identifier)

    @TestCaseMetadata(
        description="""
            This test case creates and runs a dotnet app using docker

            Steps:
            1. Install Docker
            2. Copy dotnet dockerfile into node
            3. Create docker image and run docker container
            4. Check results of docker run against dotnet string identifier
        """,
        priority=1,
    )
    def verify_docker_dotnet31_app(self, node: Node) -> None:
        self._execute_docker_test(
            node, "dotnetimage", "Hello World!", "", "dotnet31.Dockerfile"
        )

    @TestCaseMetadata(
        description="""
            This test case creates and runs a dotnet app using docker

            Steps:
            1. Install Docker
            2. Copy dotnet dockerfile into node
            3. Create docker image and run docker container
            4. Check results of docker run against dotnet string identifier
        """,
        priority=2,
    )
    def verify_docker_dotnet50_app(self, node: Node) -> None:
        self._execute_docker_test(
            node, "dotnetimage", "Hello World!", "", "dotnet50.Dockerfile"
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
        priority=2,
    )
    def verify_docker_java_app(self, node: Node) -> None:
        self._execute_docker_test(
            node,
            "javaappimage",
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
    def verify_docker_python_app(self, node: Node) -> None:
        self._execute_docker_test(
            node,
            "pythonappimage",
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
        string_identifier: str,
        prog_src: str,
        dockerfile: str,
    ) -> None:
        docker_tool = self._verify_and_remove_images(node, docker_image_name)
        if prog_src:
            self._copy_to_node(node, prog_src)
        self._copy_to_node(node, dockerfile)
        self._run_and_verify_results(
            docker_tool,
            dockerfile,
            docker_image_name,
            string_identifier,
        )

    def _run_and_verify_results(
        self,
        docker_tool: Docker,
        dockerfile_name: str,
        docker_image_name: str,
        string_identifier: str,
    ) -> None:
        docker_tool.build_image(docker_image_name, dockerfile_name)
        docker_run = docker_tool.run_container(docker_image_name)
        docker_tool.remove_image(docker_image_name)

        docker_run_output = (docker_run.stdout + docker_run.stderr).strip()
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

    def _verify_and_remove_images(self, node: Node, docker_image_name: str) -> Docker:
        self._skip_if_not_supported(node)
        try:
            docker_tool = node.tools[Docker]
        except UnsupportedDistroException as e:
            raise SkippedException(e)
        self._verify_docker_engine(node)
        docker_tool.remove_image(docker_image_name)
        return docker_tool

    def _verify_docker_engine(self, node: Node) -> None:
        node.log.debug(f"VerifyDockerEngine on {node.os.information.vendor.lower()}")
        result = node.execute(
            "docker run hello-world",
            sudo=True,
        )
        # temp solution, will revert change once newer package
        # which can fix the issue release
        # refer https://access.redhat.com/discussions/6988326
        if result.exit_code != 0 and get_matched_str(
            result.stdout, self.RHEL_ERROR_PATTERN
        ):
            if isinstance(node.os, Redhat) and node.os.information.version >= "9.0.0":
                node.os.install_packages("crun-1.4.5-2*")
                result = node.execute(
                    "docker run hello-world",
                    sudo=True,
                )

        if result.exit_code != 0 and get_matched_str(
            result.stdout, self.CENTOS_ERROR_PATTERN
        ):
            if isinstance(node.os, CentOs) and node.os.information.version >= "8.0.0":
                node.execute("rpm -e libseccomp --nodeps", sudo=True)
                node.os.install_packages(
                    "http://rpmfind.net/linux/centos/8-stream/"
                    "BaseOS/x86_64/os/Packages/libseccomp-2.5.1-1.el8.x86_64.rpm"
                )
                result = node.execute(
                    "docker run hello-world",
                    sudo=True,
                )
        assert_that(result.exit_code).described_as(
            "Fail to run docker run hello-world"
        ).is_equal_to(0)
        node.log.debug(f"VerifyDockerEngine: hello-world output - {result.stdout}")

    @TestCaseMetadata(
        description="""
            Verifies a custom Docker seccomp profile is applied and enforced.

            Steps:
            1. Install Docker on the target node
            2. Copy the custom seccomp profile that explicitly denies the chmod syscall
            3. Start a container with this custom seccomp profile and try to run chmod;
               the command should fail, proving the profile is enforced
            4. Start another container without the custom profile and run the same chmod
               command; this time it should succeed, proving the restriction only comes
               from the profile
        """,
        priority=2,
        requirement=simple_requirement(unsupported_os=[Windows, BSD]),
    )
    def verify_docker_seccomp_profile(self, node: Node) -> None:
        docker_tool = node.tools[Docker]
        docker_tool.pull_image("alpine:latest")
        if "seccomp" not in docker_tool.info().lower():
            raise SkippedException("Seccomp not supported/enabled on this Docker host")

        # Test with profile: expect failure
        self._copy_to_node(node, "deny_chmod_seccomp.json")
        profile_path = node.working_path / "deny_chmod_seccomp.json"

        test_cmd = "sh -c 'touch test_file && chmod 600 test_file'"
        denied = docker_tool.run_container(
            "alpine:latest",
            command=test_cmd,
            extra_args=f"--security-opt seccomp={profile_path}",
            expected_exit_code=None,
        )
        assert_that(denied.exit_code).described_as(
            "chmod unexpectedly succeeded under denied seccomp profile"
        ).is_not_equal_to(0)
        denied_output = (denied.stdout + denied.stderr).lower()
        assert_that(
            any(
                x in denied_output
                for x in (
                    "operation not permitted",
                    "eperm",
                )
            )
        ).described_as(
            "Did not find expected seccomp denial indicator"
            " (Operation not permitted/EPERM)"
        ).is_true()

        # Test without profile: expect success
        allowed = docker_tool.run_container(
            "alpine:latest",
            command=test_cmd,
            expected_exit_code=0,
        )
        allowed_output = (allowed.stdout + allowed.stderr).lower()
        assert_that(allowed_output).described_as(
            "Baseline run (no seccomp profile) unexpectedly showed denial text"
        ).does_not_contain("operation not permitted").does_not_contain("eperm")
