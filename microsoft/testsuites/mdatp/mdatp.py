# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import pathlib

from assertpy import fail

from lisa import Node, SkippedException, TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.operating_system import Posix
from lisa.sut_orchestrator import AZURE
from lisa.testsuite import simple_requirement

# some constants from  check-mdatp.sh
# if any mdatp install in /etc/opt is found
EXIT_MDATP_AGENT_INSTALLED = 1
# if mdatp az extension is installed
EXIT_MDE_INSTALLED = 2
# if any log dirs are found
EXIT_MDATP_LOGS_FOUND = 4
# if an installation log is found
EXIT_MDATP_INSTALL_LOGS_FOUND = 8
# if an onboarding blob is found
EXIT_ONBOARD_INFO_FOUND = 16


@TestSuiteMetadata(
    area="mdatp",
    category="functional",
    description="""
        Test to verify there are no pre-installed copies of mdatp.
    """,
)
class MdatpSuite(TestSuite):
    @TestCaseMetadata(
        description="""
           Check for mdatp endpoint/cloud install, dump config info.
           Fails if mdatp is installed in the image.
           Raises specific error messages depending on the type of info
           foud
        """,
        priority=3,
        requirement=simple_requirement(
            supported_os=[Posix], supported_platform_type=[AZURE]
        ),
    )
    def verify_mdatp_not_preinstalled(self, node: Node) -> None:
        # collect some paths before we start the test
        checker = "check-mdatp.sh"
        local_path = pathlib.PurePath(__file__).parent.joinpath(checker)
        working_path = node.get_working_path()
        script_path = working_path.joinpath(checker)

        # copy the bash script to the node
        node.shell.copy(local_path=local_path, node_path=script_path)
        result = node.execute(
            cmd=f"chmod +x {str(script_path)}",
            shell=True,
            sudo=True,
        )
        # and run the script to check and dump defender info
        result = node.execute(
            cmd=f"{str(script_path)}",
            shell=True,
            sudo=True,
            no_debug_log=True,
        )
        script_output = result.stdout.strip()
        exit_code = result.exit_code
        if exit_code is None:
            raise SkippedException("exit code was None after running check-mdatp")
        if exit_code == 0:
            node.log.info("No mdatp onboarding info found, image is clean.")
            return

        node.log.info("Found mdatp installation!")
        node.log.debug(f"Found config information: {script_output}")
        found_onboarding_info = exit_code & EXIT_ONBOARD_INFO_FOUND
        found_install_logs = exit_code & (
            EXIT_MDATP_INSTALL_LOGS_FOUND | EXIT_MDATP_LOGS_FOUND
        )
        found_mdatp_installed = exit_code & EXIT_MDATP_AGENT_INSTALLED
        found_mde_extension_install = exit_code & EXIT_MDE_INSTALLED

        # Add some descriptive text to describe each specific problem.
        error_header = ""
        if found_onboarding_info:
            error_header += "mdatp onboarding info is present in this image! "
        if found_install_logs:
            error_header += "mdatp install logs are present in this image! "
        if found_mdatp_installed:
            error_header += "mdatp installation was found on this image! "
        if found_mde_extension_install:
            error_header += "MDE extension installation was found in this image! "
        if not any(
            [
                found_onboarding_info,
                found_install_logs,
                found_mdatp_installed,
                found_mde_extension_install,
            ]
        ):
            raise SkippedException(
                f"No recognized error code was found: {exit_code} output: {script_output}"
            )
        # set the error message depending on the info found by the script.

        error_message = (
            f"{error_header}"
            "This may indicate the VM used to build this image was "
            "onboarded to mdatp and the onboarding info was not "
            "wiped before generalizing the image. Alert the publisher "
            "that their image contains leftover logs and "
            "organization info. They can use our script to check "
            "for leftover config and org info: "
            "https://github.com/microsoft/lisa/tree/main/microsoft"
            "/testsuites/mdatp/check-mdatp.sh"
        )
        # fail and raise the error message
        fail(str(error_message))


# NOTE: it's possible there will be an additional case added
# to handle filtering the result to check for expected
# installations. For now, since there are none, we fail for
# all cases other than 'no mdatp installed by default'
