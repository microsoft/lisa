# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re

from lisa import (
    LisaException,
    Node,
    SkippedException,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
)
from lisa.environment import Environment
from lisa.operating_system import Debian, Redhat, Suse, Ubuntu
from lisa.tools import Echo, Wget
from lisa.util import find_patterns_in_lines


@TestSuiteMetadata(
    area="tvm",
    category="functional",
    description="""
    This test suite is to validate secureboot in Linux VM.
    """,
)
class TvmTest(TestSuite):
    @TestCaseMetadata(
        description="""
        """,
        priority=2,
    )
    def verify_secureboot_compatibility(
        self, node: Node, environment: Environment
    ) -> None:
        echo = node.tools[Echo]
        if isinstance(node.os, Redhat):
            content = "\n".join(
                [
                    "[packages-microsoft-com-azurecore]",
                    "name=packages-microsoft-com-azurecore",
                    "baseurl=https://packages.microsoft.com/yumrepos/azurecore/",  # noqa: E501
                    "enabled=1",
                    "gpgcheck=0",
                ]
            )
            repo_file = "/etc/yum.repos.d/azurecore.repo"
            cmd_result = node.execute(f"ls -lt {repo_file}", shell=True)
            if cmd_result.exit_code == 0:
                node.execute(f"rm -rf {repo_file}", sudo=True)
            echo.write_to_file(
                content,
                node.get_pure_path(repo_file),
                append=True,
                sudo=True,
            )
        elif isinstance(node.os, Debian):
            content = "\n".join(
                [
                    "deb [arch=amd64] http://packages.microsoft.com/repos/azurecore/ trusty main",  # noqa: E501
                    "deb [arch=amd64] http://packages.microsoft.com/repos/azurecore/ xenial main",  # noqa: E501
                    "deb [arch=amd64] http://packages.microsoft.com/repos/azurecore/ bionic main",  # noqa: E501
                ]
            )
            repo_file = "/etc/apt/sources.list.d/azure.list"
            cmd_result = node.execute(f"ls -lt {repo_file}", shell=True)
            if cmd_result.exit_code == 0:
                node.execute(f"rm -rf {repo_file}", sudo=True)
            if not isinstance(node.os, Ubuntu):
                node.os.install_packages("gnupg")
            echo.write_to_file(
                content,
                node.get_pure_path(repo_file),
                append=True,
                sudo=True,
            )
            wget = node.tools[Wget]
            wget.get(
                "https://packages.microsoft.com/keys/microsoft.asc",
                file_path=".",
                filename="microsoft.asc",
            )
            wget.get(
                "https://packages.microsoft.com/keys/msopentech.asc",
                file_path=".",
                filename="msopentech.asc",
            )
            node.execute("apt-key add microsoft.asc", sudo=True)
            node.execute("apt-key add msopentech.asc", sudo=True)
        elif isinstance(node.os, Suse):
            node.execute(
                "zypper ar -t rpm-md -n 'packages-microsoft-com-azurecore'"
                " --no-gpgcheck https://packages.microsoft.com/yumrepos/azurecore/"
                " azurecore",
                sudo=True,
            )
        else:
            raise SkippedException(f"current os {node.os.name} doesn't support tvm")
        node.os._initialize_package_installation()
        node.os.install_packages("azure-security")
        cmd_result = node.execute("/usr/local/bin/sbinfo", sudo=True)
        secure_boot_pattern = re.compile(
            r"(.*\"SBEnforcementStage\": \"Secure Boot (is|is not) enforced\".*)$", re.M
        )
        matched = find_patterns_in_lines(cmd_result.stdout, [secure_boot_pattern])
        if not (matched and matched[0]):
            raise LisaException("This OS image is not compatible with Secure Boot.")

    @TestCaseMetadata(
        description="""
        """,
        priority=2,
    )
    def verify_measuredboot_compatibility(
        self, node: Node, environment: Environment
    ) -> None:
        ...
