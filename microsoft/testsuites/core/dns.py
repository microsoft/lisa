# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from __future__ import annotations

import re

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
    retry_without_exceptions,
)


@TestSuiteMetadata(
    area="core",
    category="functional",
    description="""
    This test suite covers DNS name resolution functionality.
    """,
)
class Dns(TestSuite):
    # unattended-upgrade -d -v
    # Traceback (most recent call last):
    # File "/usr/bin/unattended-upgrade", line 74, in <module>
    #     import apt_inst
    # ModuleNotFoundError: No module named 'apt_inst'
    _fail_to_install_package_pattern = re.compile(
        r"ModuleNotFoundError: No module named \'apt_inst\'", re.M
    )

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

        except (ReleaseEndOfLifeException, RepoNotExistException) as e:
            # If the release is end of life, or there is no repo existing,
            # then skip the step of upgrading system. Continue the following test
            node.log.debug(e)
            raise PassedException(e) from e

        finally:
            self._check_dns_name_resolution(node)
            node.reboot()
            self._check_dns_name_resolution(node)

    @retry_without_exceptions(
        tries=10,
        delay=0.5,
        skipped_exceptions=[ReleaseEndOfLifeException, RepoNotExistException],
    )
    def _check_dns_name_resolution(self, node: Node) -> None:
        ping = node.tools[Ping]
        try:
            ping.ping(target="bing.com")
        except Exception as e:
            if ping.no_sendmsg_permission_pattern.findall(str(e)):
                # ping ICMP packet might be blocked by control plane ACL
                # Use "nslookup bing.com" command to check
                node.execute("nslookup bing.com", expected_exit_code=0, timeout=30)
            else:
                raise LisaException(e)

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
            if type(node.os) is Debian:
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
            result = node.execute(
                "apt update && unattended-upgrade -d -v",
                sudo=True,
                shell=True,
                timeout=2400,
            )
            if result.exit_code != 0 and self._fail_to_install_package_pattern.findall(
                result.stdout
            ):
                node.execute(
                    "apt install --reinstall python3 python python3-minimal "
                    "--fix-broken",
                    sudo=True,
                    shell=True,
                )
                result = node.execute(
                    "apt update && unattended-upgrade -d -v",
                    sudo=True,
                    shell=True,
                    timeout=2400,
                )
            if result.exit_code != 0:
                # make node as dirty, so the node will be not used in next test case
                node.mark_dirty()
                raise LisaException(
                    "fail to run apt update && unattended-upgrade -d -v"
                )
