# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from __future__ import annotations

from retry import retry

from lisa import (
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    UnsupportedDistroException,
)
from lisa.operating_system import Debian, Posix
from lisa.tools import Ping
from lisa.util import (
    LisaException,
    PassedException,
    ReleaseEndOfLifeException,
    RepoNotExistException,
)


@TestSuiteMetadata(
    area="core",
    category="functional",
    description="""
    This test suite covers DNS name resolution functionality.
    """,
)
class Dns(TestSuite):
    @TestCaseMetadata(
        description="""
        This test case check DNS name resolution by ping bing.com.
        """,
        priority=1,
    )
    def verify_dns_name_resolution(self, node: Node) -> None:
        self._check_dns_name_resolution(node)

    @TestCaseMetadata(
        description="""
        This test case check DNS name resolution by ping bing.com after upgrade system.
        """,
        priority=1,
    )
    def verify_dns_name_resolution_after_upgrade(self, node: Node) -> None:
        self._check_dns_name_resolution(node)

        try:
            self._upgrade_system(node)

        except (ReleaseEndOfLifeException, RepoNotExistException) as identifier:
            # If the release is end of life, or there is no repo existing,
            # then skip the step of upgrading system. Continue the following test
            node.log.debug(identifier)
            raise PassedException(identifier) from identifier

        finally:
            self._check_dns_name_resolution(node)
            node.reboot()
            self._check_dns_name_resolution(node)

    @retry(tries=10, delay=0.5)
    def _check_dns_name_resolution(self, node: Node) -> None:
        ping = node.tools[Ping]
        try:
            ping.ping(target="bing.com")
        except Exception as identifier:
            if ping.no_sendmsg_permission_pattern.findall(str(identifier)):
                # ping ICMP packet might be blocked by control plane ACL
                # Use "nslookup bing.com" command to check
                node.execute("nslookup bing.com", expected_exit_code=0, timeout=30)
            else:
                raise LisaException(identifier)

    def _upgrade_system(self, node: Node) -> None:
        if not isinstance(node.os, Posix):
            raise UnsupportedDistroException(node.os)

        node.os.update_packages("")
        if isinstance(node.os, Debian):
            cmd_result = node.execute(
                "which unattended-upgrade",
                sudo=True,
                shell=True,
            )
            if 0 != cmd_result.exit_code:
                node.os.install_packages("unattended-upgrades")
            if type(node.os) == Debian:
                if node.os.information.version >= "10.0.0":
                    node.execute(
                        "mkdir -p /var/cache/apt/archives/partial",
                        sudo=True,
                        shell=True,
                        expected_exit_code=0,
                        expected_exit_code_failure_message=(
                            "fail to make folder /var/cache/apt/archives/partial"
                        ),
                    )
                else:
                    node.os.install_packages(
                        ["debian-keyring", "debian-archive-keyring"]
                    )
            node.execute(
                "apt update && unattended-upgrade -d -v",
                sudo=True,
                shell=True,
                expected_exit_code=0,
                expected_exit_code_failure_message="fail to run unattended-upgrade",
                timeout=2400,
            )
