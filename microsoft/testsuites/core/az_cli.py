# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from __future__ import annotations

from lisa import Logger, Node, TestCaseMetadata, TestSuite, TestSuiteMetadata


@TestSuiteMetadata(
    area="core",
    category="functional",
    description="""
    """,
)
class AzCLI(TestSuite):
    @TestCaseMetadata(
        description="""Az CLI checks""",
        priority=2,
    )
    def az_cli_test(self, node: Node, log: Logger) -> None:
        node.execute(
            "curl -sL https://aka.ms/InstallAzureCLIDeb | bash", sudo=True, shell=True
        )
        node.execute("az --version", shell=True, sudo=True)
        node.execute(
            "az login --use-device-code",
            sudo=True,
            shell=True,
        )

        # run a command to verify that the login was successful
        node.execute("az account show", shell=True, sudo=True)
