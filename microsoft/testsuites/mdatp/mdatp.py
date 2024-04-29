# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import pathlib

from assertpy import fail

from lisa import Node, TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.operating_system import Windows
from lisa.sut_orchestrator import AZURE
from lisa.testsuite import simple_requirement
from lisa.tools import Df, Mount
from lisa.tools.lsblk import PartitionInfo

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


def apply_working_path_noexec_workaround(node: Node) -> None:
    # EXAMPLE WORKAROUND:
    # - Get the mount point for the path.
    # - Check if the mount point is mounted noexec.
    # - if yes, remount with exec flag
    working_path = node.get_working_path()
    mount_info = node.tools[Df].get_partition_by_path(directory=working_path.as_posix())
    if mount_info and check_noexec_partition(node, mount_info):
        node.log.info(f"Working path in {mount_info.mountpoint} is mounted noexec!!")
        remount_with_exec(node, mount_info)
    elif not mount_info:
        # info only, since nearly all (99.99%) of images do not
        # require this workaround. An image with weird DF or Mount
        # output should still be able to run the script, so we
        # will info and allow the test to continue.
        node.log.info(
            f"Could not locate mount info for directory "
            f"{working_path.as_posix()}. "
            "Test may fail due to noexec permissions error. "
            "Or due to the working path not existing."
        )

    # no issues with partition, nothing to fix.
    return


def check_noexec_partition(node: Node, partition: PartitionInfo) -> bool:
    # an example. I don't have time to implement this in mount,
    # we currently discard the mount options so they're not exposed
    # in tools.Mount
    for part in node.tools[Mount].get_partition_info():
        node.log.debug(f"checking partition {str(part)}...")
        if part.mount_point == partition.mountpoint:
            return "noexec" in part.options
    # This path would mean that df and mount are returning different
    # info about the mount points on the VM.
    # There should be no way for this to happen, assert if it does
    node.log.info(
        f"Could not find partition info for {partition.mountpoint}! "
        "This indicates that LISA could not properly parse the output "
        "of 'mount' and 'df'. It's possible this image does not have "
        "these tools available. "
        "Note: This is a non-fatal error for the mdatp test. "
        "Resuming text execution..."
    )
    # appease pylint by returning after assert
    return False


def remount_with_exec(node: Node, partition: PartitionInfo) -> None:
    # Fix issue where working path is created in a partition marked
    # 'noexec' meaning file permissions for x are ignored.
    # Attempt to remount the parition to allow executables.
    # The other fix would just be adding a disk, creating a parition
    # marking it executable, and using that as the working path.
    node.tools[Mount].mount(
        options="remount,exec",
        point=partition.mountpoint,
        name=partition.name,
    )


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

        # call the example workaround, see function for details.
        # TODO: remove this when the fix is implemented
        apply_working_path_noexec_workaround(node)

        result = node.execute(
            cmd=f"chmod a+x,a+r,a-w {str(script_path)}",
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
            fail(
                # make this better
                "The check for leftover mdatp/defender installations returned an "
                f"unexpected exit code ({exit_code}). This implies that the image "
                "may not have a posix-compliant shell, the image itself may be "
                "unstable, or an OS error occurred while attempting to run "
                "https://aka.ms/mdatp-check-sh. Our test is unable to certify "
                "that mdatp/defender was uninstalled before "
                "generalizing the image. Please verify that you have "
                "cleared your image of any mdatp/defender data before "
                "generalizing, then raise an issue at: "
                "https://www.github.com/microsoft/lisa. "
                "If your image has a posix shell available, ensure that "
                "the script at https://aka.ms/mdatp-check-sh runs and "
                "returns 0 before opening a Github issue. "
                f"script_output: {script_output}"
            )

        # active voice, explain problem and give clear instructions
        # set the error message depending on the info found by the script.
        error_message = (
            f"{error_header}"
            "This indicates mdatp/defender was not removed prior to "
            "generalizing the image. Remove this installation by "
            "following the steps here: "
            "https://aka.ms/uninstall-defender-linux."
            "Before resubmitting this image, validate that the script "
            "at https://aka.ms/mdatp-check-sh runs and returns 0. "
            "If you believe this failure is an error, please raise an "
            "issue at https://www.github.com/microsoft/lisa."
        )
        # fail and raise the error message
        fail(str(error_message))


# NOTE: it's possible there will be an change eventually to support
# publisher's pre-installing defender without activating it,
# without an onboarding blob, without a service enabled to auto-start it.
# This does not happen currently, it's expected (and recommended) people
# will pick and install their own antivirus.
