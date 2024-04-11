# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import pathlib

from assertpy import fail

from lisa import Node, SkippedException, TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.operating_system import Windows
from lisa.sut_orchestrator import AZURE
from lisa.testsuite import simple_requirement

# some constants from  check-mdatp.sh
# if any mdatp install in /etc/opt is found
EXIT_MDATP_AGENT_INSTALLED = 251
# if mdatp az extension is installed
EXIT_MDE_INSTALLED = 252
# if any log dirs are found
EXIT_MDATP_LOGS_FOUND = 253
# if an installation log is found
EXIT_MDATP_INSTALL_LOGS_FOUND = 254
# if an onboarding blob is found
EXIT_ONBOARD_INFO_FOUND = 255


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
           found
        """,
        priority=3,
        requirement=simple_requirement(
            unsupported_os=[Windows], supported_platform_type=[AZURE]
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
        assert exit_code is not None, "exit code was None after running check-mdatp"

        # pass if no pre-installed copy of defender is found.
        if exit_code == 0:
            node.log.info("No mdatp onboarding info found, image is clean.")
            return

        # otherwise, some remnant of defender was found in the image.
        node.log.info("Found mdatp installation!")
        node.log.debug(f"Found config information: {script_output}")

        # check the exit code to determine which info was found.
        found_onboarding_info = exit_code == EXIT_ONBOARD_INFO_FOUND
        found_install_logs = (
            exit_code == EXIT_MDATP_INSTALL_LOGS_FOUND
            or exit_code == EXIT_MDATP_LOGS_FOUND
        )

        found_mdatp_installed = exit_code == EXIT_MDATP_AGENT_INSTALLED
        found_mde_extension_install = exit_code == EXIT_MDE_INSTALLED

        # Add some descriptive text to describe each specific problem.
        error_header = ""
        if found_onboarding_info:
            error_header = "mdatp onboarding info is present in this image! "
        elif found_install_logs:
            error_header = "mdatp install logs are present in this image! "
        elif found_mdatp_installed:
            error_header = "mdatp installation was found on this image! "
        elif found_mde_extension_install:
            error_header = "MDE extension installation was found in this image! "
        else:
            # if exit code is unexpected, something is off with the test.
            # We can't 'pass', since the image is neither clean nor dirty.
            # Maybe it's ReactOS? Who knows. We'll find out if we ever hit this path.
            raise SkippedException(
                "Unrecognized exit code (is this a non-posix compliant shell?): "
                f"{exit_code} script_output: {script_output}"
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


# NOTE: it's possible there will be an change eventually to support
# publisher's pre-installing defender without activating it,
# without an onboarding blob, without a service enabled to auto-start it.
# This does not happen currently, it's expected (and recommended) people
# will pick and install their own antivirus.
