# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import time
import xml.etree.ElementTree as ETree
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Any, List, Type, cast

from assertpy.assertpy import assert_that

from lisa.executable import Tool
from lisa.messages import TestStatus, send_sub_test_result_message
from lisa.operating_system import CBLMariner, Posix, Ubuntu
from lisa.testsuite import TestResult
from lisa.tools import Chmod, Echo, Git, Sed, Service, Usermod


@dataclass
class LibvirtTckTestResult:
    name: str = ""
    status: TestStatus = TestStatus.QUEUED


class LibvirtTck(Tool):
    TIME_OUT = 3600

    # The failures in these tests need to be investigated and fixed. Until then, treat
    # them as expected failures.
    EXPECTED_FAILURES = {
        CBLMariner.__name__: [
            "nwfilter_050-apply-verify-host_t",
        ],
        Ubuntu.__name__: [
            "100-apply-verify-host_t",
            "220-no-ip-spoofing_t",
            "230-no-mac-broadcast_t",
        ],
    }

    repo = "https://gitlab.com/libvirt/libvirt-tck.git"
    deps = [
        "cpanminus",
        "expat-devel",
        "gcc",
        "glibc-devel",
        "kernel-headers",
        "libguestfs-tools",
        "libsys-virt-perl",
        "libtest-xml-perl",
        "libvirt",
        "libvirt-client",
        "libvirt-daemon-system",
        "libvirt-dev",
        "make",
        "perl",
        "perl-App-cpanminus",
        "perl-Sys-Virt",
        "perl-XML-SAX",
        "qemu-kvm",
        "qemu-system-x86",
    ]

    repo_root: PurePath

    @property
    def command(self) -> str:
        return "libvirt-tck"

    @property
    def can_install(self) -> bool:
        return True

    @property
    def dependencies(self) -> List[Type[Tool]]:
        return [Git]

    def run_tests(
        self,
        test_result: TestResult,
        log_path: Path,
    ) -> None:
        result = self.run(
            "--force --format junit -a results.tar.gz",
            timeout=self.TIME_OUT,
            force_run=True,
            cwd=self.repo_root,
            sudo=True,
            shell=True,
        )

        results = self._extract_test_results(result.stdout)
        failures = [r.name for r in results if r.status == TestStatus.FAILED]
        expected_fails = [r.name for r in results if r.status == TestStatus.ATTEMPTED]
        if not failures and not expected_fails:
            result.assert_exit_code()

        for r in results:
            send_sub_test_result_message(
                test_result=test_result,
                test_case_name=r.name,
                test_status=r.status,
            )

        archive_path = self.repo_root / "results.tar.gz"
        self.node.tools[Chmod].chmod(str(archive_path), "a+r", sudo=True)
        self.node.shell.copy_back(
            self.repo_root / "results.tar.gz",
            log_path / "libvirt_tck_results.tar.gz",
        )
        assert_that(failures, f"Unexpected failures: {failures}").is_empty()

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        tool_path = self.get_tool_path(use_global=True)
        self.repo_root = tool_path / "libvirt-tck"

    def _install_dep(self) -> None:
        posix_os: Posix = cast(Posix, self.node.os)
        git = self.node.tools[Git]
        git.clone(self.repo, self.get_tool_path(use_global=True), fail_on_exists=False)

        # install dependency packages
        for package in list(self.deps):
            if posix_os.is_package_in_repo(package):
                posix_os.install_packages(package)

    def _install(self) -> bool:
        self._install_dep()

        if isinstance(self.node.os, CBLMariner):
            # tell libvirt to run qemu as root
            libvirt_qemu_conf = PurePath("/etc/libvirt/qemu.conf")
            self.node.tools[Echo].write_to_file(
                'user = "root"'.replace('"', '\\"'),
                libvirt_qemu_conf,
                sudo=True,
                append=True,
            )
            self.node.tools[Echo].write_to_file(
                'group = "root"'.replace('"', '\\"'),
                libvirt_qemu_conf,
                sudo=True,
                append=True,
            )

            self.node.tools[Usermod].add_user_to_group("libvirt", sudo=True)

            # Workaround for error:
            #
            # error from service: GDBus.Error:org.gtk.GDBus.UnmappedGError.Quark
            # ._g_2dfile_2derror_2dquark.Code4: Failed to open file
            # “/proc/2192/status”: No such file or directory
            self.node.tools[Sed].substitute(
                "hidepid=2",
                "hidepid=0",
                "/etc/fstab",
                sudo=True,
            )

            self.node.reboot(time_out=900)

            # After reboot, libvirtd service is in failed state and needs to
            # be restarted manually. Doing it immediately after restarts
            # fails. So wait for a while before restarting libvirtd.
            # This is an issue in Mariner and below lines can be removed once
            # it has been addressed.
            tries = 0
            while tries <= 10:
                try:
                    self.node.tools[Service].restart_service("libvirtd")
                    break
                except Exception:
                    time.sleep(1)
                    tries += 1

        modules_to_install = " ".join(
            [
                "inc::latest",
                "Module::Build",
                "IO::Interface::Simple",
                "Net::OpenSSH",
            ]
        )
        self.node.execute(
            f"cpanm install {modules_to_install}",
            sudo=True,
            timeout=self.TIME_OUT,
        )
        self.node.execute(
            "perl Build.PL", cwd=self.repo_root, expected_exit_code=0, sudo=True
        )
        self.node.execute(
            "cpanm --installdeps .",
            cwd=self.repo_root,
            sudo=True,
            expected_exit_code=0,
            timeout=self.TIME_OUT,
        )
        self.node.execute(
            "./Build install", cwd=self.repo_root, sudo=True, expected_exit_code=0
        )

        return self._check_exists()

    def _is_expected_failure(self, name: str) -> bool:
        distro = type(self.node.os).__name__
        # The test name in the output appears with its full path. Whereas the
        # self.EXPECTED_FAILURES contain just the test names. That's why
        # endswith() is used here.
        return len([f for f in self.EXPECTED_FAILURES[distro] if name.endswith(f)]) > 0

    def _extract_test_results(self, output: str) -> List[LibvirtTckTestResult]:
        results: List[LibvirtTckTestResult] = []

        # output follows the JUnit XML schema
        testsuites = ETree.fromstring(output)
        for testsuite in testsuites:
            result = LibvirtTckTestResult()

            result.name = testsuite.attrib["name"]
            skipped = int(testsuite.attrib["tests"]) == 0
            failed = int(testsuite.attrib["failures"]) > 0
            if failed:
                if self._is_expected_failure(result.name):
                    result.status = TestStatus.ATTEMPTED
                else:
                    result.status = TestStatus.FAILED
            elif skipped:
                result.status = TestStatus.SKIPPED
            else:
                result.status = TestStatus.PASSED

            results.append(result)

        return results
