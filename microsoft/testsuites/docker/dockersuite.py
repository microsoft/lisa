# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import Path

from assertpy import assert_that

from lisa import (
    Node,
    SkippedException,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
)
from lisa.tools.docker import Docker #will be changed
from lisa.util import LisaException, constants

DOCKERFILE_NAME="Dockerfile"

DOCKER_BUILD_OUTPUT : str = "docker_build.log" # cleanup
DOCKER_RUN_OUTPUT : str = "docker_run.log" # cleanup

JAVA_STRING_IDENTIFIER : str = "Hello world from java"
JAVA_PROG_APP="Main"
JAVA_PROG_SRC="Main.java"

@TestSuiteMetadata(
    area="docker",
    category="functional",
    description="""
    This test suite runs the docker test cases.
    """,
)
class docker(TestSuite):

    def _generate_file(content : str, path : Path):
        #need to check if file already exists
        if path.exists():
            raise LisaException(f"Generating {path} but the file already exists.")

        with open(path, "w") as file: 
            file.write(content)


    def _check_dotnet_sdk_support(node : Node, package_name : str) -> bool:
        exit_status = node.execute(f"curl --head --silent --fail {package_name}")
        if not exit_status == 0:
            raise LisaException(f"{package_name} not available")
        return True

    def _install_dotnet_sdk():
        pass

    def _compile_dotnet_app():
        pass


    @TestCaseMetadata(
        description="""
            This test case ...

            Steps:
            1. x
            2. x
        """,
        priority=0,
    )
    def docker_java_app(self, node: Node):
        docker_tool = node.tools[Docker]

        # I omitted RemoveDockerContainer and RemoveDockerImage for now because
        # it looks that it would cause an error any time called
        self.__log("Generating Java Program.")
        java_file_contents = """public class Main
{
    public static void main(String[] args) {
        System.out.println("{JAVA_STRING_IDENTIFIER}");
    }
}
        """
        java_file_contents.format(JAVA_STRING_IDENTIFIER = JAVA_STRING_IDENTIFIER)
        self._generate_file(java_file_contents, JAVA_PROG_SRC)

        self.__log("Generating Dockerfile.")
        docker_file_path = Path(constants.RUN_LOCAL_PATH / JAVA_PROG_SRC)
        docker_file_contents = """FROM alpine
        WORKDIR /usr/src/myapp
        COPY {JAVA_PROG_SRC} /usr/src/myapp
        #install jdk
        RUN apk add openjdk8
        ENV JAVA_HOME /usr/lib/jvm/java-1.8-openjdk
        ENV PATH \$PATH:\$JAVA_HOME/bin
        #compile program
        RUN javac {JAVA_PROG_SRC}
        ENTRYPOINT java {JAVA_PROG_APP}
        """ # clean this up
        docker_file_contents.format(
            JAVA_PROG_SRC = docker_file_path,
            JAVA_PROG_APP = JAVA_PROG_APP,
            JAVA_STRING_IDENTIFIER = JAVA_STRING_IDENTIFIER
        )
        self._generate_file(docker_file_contents, docker_file_path)

        docker_file_path = Path(constants.RUN_LOCAL_PATH / DOCKERFILE_NAME) # cleanup

        container_name ="javaapp"
        docker_image_name ="javaappimage"
        docker_tool._build_docker_image(container_name, str(docker_file_path))
        docker_tool._run_docker_container(docker_image_name, container_name)

        with open(DOCKER_RUN_OUTPUT, "r") as output_file:
            assert_that(
                JAVA_STRING_IDENTIFIER in output_file.read()
            ).is_true()

    def docker_dotnet_app(self, node: Node):
        pass
