# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import pathlib

from lisa import Node, SkippedException, TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.operating_system import Linux
from lisa.sut_orchestrator import AZURE
from lisa.testsuite import simple_requirement


@TestSuiteMetadata(
    area="mdatp",
    category="functional",
    description="""
        Tests to check and validate mdatp config info in an Azure marketplace image.
    """,
)
class MdatpSuite(TestSuite):
    @TestCaseMetadata(
        description="""
           Check for mdatp endpoint/cloud install, dump config info.
        """,
        priority=3,
        requirement=simple_requirement(
            supported_os=[Linux], supported_platform_type=[AZURE]
        ),
    )
    def verify_mdatp_config(self, node: Node) -> None:
        # check bash is available
        if not node.execute("command -v bash", shell=True, sudo=True):
            raise SkippedException("No bash installation was found! Skipping test...")

        # collect some paths before we start the test
        local_path = pathlib.PurePath(__file__).parent.joinpath("check-mdatp.sh")
        working_path = node.get_working_path()
        node_script_path = working_path.joinpath("check-mdatp.sh")

        # copy the bash script to the node
        node.shell.copy(local_path=local_path, node_path=node_script_path)
        result = node.execute(
            cmd=f"chmod +x {str(node_script_path)}",
            shell=True,
            sudo=True,
        )
        # and run the script to check and dump defender info
        result = node.execute(
            cmd=f"bash +x {str(node_script_path)}",
            shell=True,
            sudo=True,
        )
        script_output = result.stdout.strip()
        exit_code = result.exit_code
        if exit_code != 0:
            raise SkippedException("Did not find mdatp installation on this VM.")

        node.log.info("Found mdatp installation!")
        node.log.info(f"Found config information: {script_output}")
