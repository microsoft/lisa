# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from __future__ import annotations

import re
import time
from typing import Any

from lisa import (
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    UnsupportedDistroException,
)
from lisa.executable import ExecutableResult
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
    # unattended-upgrade prints this once all applicable upgrades are applied.
    _upgrade_success_pattern = re.compile(r"All upgrades installed", re.M)
    # Genuine failures from apt/dpkg. unattended-upgrade returns a non-zero exit
    # code when it only holds back packages (conffile prompts, blacklisted or
    # pinned packages such as ubuntu-pro-client on FDE/Ubuntu Pro images), which
    # is not a real failure; these markers distinguish an actual error.
    _upgrade_real_error_pattern = re.compile(
        r"^(?:dpkg: error|E: |Errors were encountered)|"
        r"not fully installed|"
        r"Sub-process /usr/bin/dpkg returned an error",
        re.M,
    )
    # unattended-upgrade and apt exit right away when another package process
    # still holds the apt/dpkg lock, e.g. just after "apt-get upgrade".
    _package_lock_error_pattern = re.compile(
        r"Lock could not be acquired|"
        r"Cache lock can not be acquired|"
        r"Could not get lock",
        re.M,
    )
    _unattended_upgrade_attempts = 5
    _unattended_upgrade_retry_delay_seconds = 10

    def after_case(self, log: Logger, **kwargs: Any) -> None:
        log.debug("after_case: mark node as dirty to avoid affecting other test cases")
        node = kwargs["node"]
        node.mark_dirty()

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
            node.log.debug(f"ping bing.com failed: {e}")
            # ping ICMP packet might be blocked by control plane ACL
            # Use "nslookup bing.com" command to check
            cmd_execute = node.execute("nslookup bing.com", timeout=30)
            if cmd_execute.exit_code != 0:
                raise LisaException(
                    f"DNS name resolution failed by nslookup: {cmd_execute.stdout}"
                )

    def _run_unattended_upgrade(
        self, node: Node, debian_os: Debian
    ) -> ExecutableResult:
        # The previous package step can leave a short-lived apt/dpkg process
        # holding the lock, so wait for it and retry on lock errors instead
        # of failing on the first attempt.
        attempt = 1
        while True:
            debian_os.wait_running_package_process()
            result = node.execute(
                "apt update && unattended-upgrade -d -v",
                sudo=True,
                shell=True,
                timeout=2400,
            )
            output = (result.stdout or "") + (result.stderr or "")
            if (
                result.exit_code == 0
                or not self._package_lock_error_pattern.search(output)
                or attempt >= self._unattended_upgrade_attempts
            ):
                return result
            node.log.debug(
                "apt/unattended-upgrade could not acquire the package lock "
                f"(attempt {attempt}/{self._unattended_upgrade_attempts}), "
                "waiting and retrying."
            )
            attempt += 1
            time.sleep(self._unattended_upgrade_retry_delay_seconds)

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
            result = self._run_unattended_upgrade(node, node.os)
            if result.exit_code != 0 and self._fail_to_install_package_pattern.findall(
                result.stdout
            ):
                node.execute(
                    "apt install --reinstall python3 python python3-minimal "
                    "--fix-broken",
                    sudo=True,
                    shell=True,
                )
                result = self._run_unattended_upgrade(node, node.os)
            if result.exit_code != 0:
                combined_output = (result.stdout or "") + (result.stderr or "")
                upgrade_succeeded = bool(
                    self._upgrade_success_pattern.search(combined_output)
                )
                has_real_error = bool(
                    self._upgrade_real_error_pattern.search(combined_output)
                )
                if upgrade_succeeded and not has_real_error:
                    # unattended-upgrade returns a non-zero exit code when it
                    # holds back packages (conffile prompts, blacklisted or
                    # pinned packages such as ubuntu-pro-client on FDE/Ubuntu
                    # Pro images) even though all applicable upgrades installed
                    # successfully. This is not a failure for this test.
                    node.log.info(
                        "unattended-upgrade reported 'All upgrades installed' "
                        f"with exit code {result.exit_code}; treating held-back "
                        "packages as a non-fatal condition."
                    )
                else:
                    raise LisaException(
                        "fail to run apt update && unattended-upgrade -d -v"
                    )
