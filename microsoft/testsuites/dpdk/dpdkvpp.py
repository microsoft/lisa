# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import time
from typing import List, Type

from assertpy import assert_that

from lisa.executable import Tool
from lisa.operating_system import Debian, Fedora, Suse
from lisa.tools import Cat, Echo, Gcc, Git, Make, Modprobe
from lisa.util import SkippedException, UnsupportedDistroException


class DpdkVpp(Tool):
    VPP_SRC_LINK = "https://github.com/FDio/vpp.git"
    REPO_DIR = "vpp"
    START_UP_FILE = "/etc/vpp/startup.conf"

    @property
    def command(self) -> str:
        return "vpp"

    @property
    def dependencies(self) -> List[Type[Tool]]:
        # dependencies are needed for build script! Don't delete
        return [Gcc, Make, Git]

    @property
    def can_install(self) -> bool:
        # vpp supports any .deb or .rpm based install
        # including SUSE
        return (
            isinstance(self.node.os, Fedora)
            or isinstance(self.node.os, Debian)
            or isinstance(self.node.os, Suse)
        )

    def start(self) -> None:
        node = self.node
        modprobe = node.tools[Modprobe]
        if isinstance(node.os, Fedora):
            # Fedora/RHEL has strict selinux by default,
            # this messes with the default vpp settings.
            # quick fix is setting permissive mode
            node.execute(
                "setenforce Permissive",
                sudo=True,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    "Could not set selinux to permissive"
                ),
            )

        # It is possible the service has already been started, so
        # rather than assume anything we'll call restart
        # this will force the reload if it's already started
        # or start it if it hasn't started yet.
        modprobe.load("uio_hv_generic")
        self.run_async(f"-c {self.START_UP_FILE}", force_run=True, sudo=True)
        time.sleep(3)  # give it a moment to start up

    def get_start_up_file_content(self, force_run: bool = False) -> str:
        cat = self.node.tools[Cat]
        start_up_conf = ""
        start_up_conf = cat.read(self.START_UP_FILE, sudo=True, force_run=force_run)
        return start_up_conf

    def set_start_up_file(self, setting: str) -> None:
        setting = f"dpdk {{{setting}}}"
        self.node.tools[Echo].write_to_file(
            setting, self.node.get_pure_path(self.START_UP_FILE), append=True, sudo=True
        )

    def run_test(self) -> None:
        node = self.node
        vpp_interface_output = node.execute(
            "vppctl show int",
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "VPP returned error code while gathering interface info"
            ),
        ).stdout
        vpp_detected_interface = (
            "GigabitEthernet" in vpp_interface_output
            or "VirtualFunctionEthernet" in vpp_interface_output
        )
        assert_that(vpp_detected_interface).described_as(
            "VPP did not detect the dpdk VF or Gigabit network interface"
        ).is_true()

    def _install(self) -> bool:
        node = self.node
        if isinstance(node.os, Fedora):
            node.os.install_epel()
        if isinstance(node.os, Debian):
            pkg_type = "deb"
        elif isinstance(node.os, Fedora) or isinstance(node.os, Suse):
            pkg_type = "rpm"
        else:
            raise SkippedException(
                UnsupportedDistroException(
                    self.node.os, "VPP is not supported on this OS"
                )
            )

        node.execute(
            (
                "curl -s https://packagecloud.io/install/repositories/fdio/release/"
                f"script.{pkg_type}.sh | sudo bash"
            ),
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "Could not install vpp with fdio provided installer"
            ),
        )
        node.os.update_packages("")
        self._install_from_package_manager()
        return True

    def _install_from_package_manager(self) -> None:
        node = self.node
        vpp_packages = ["vpp"]

        if isinstance(node.os, Debian):
            vpp_packages += ["vpp-plugin-dpdk", "vpp-plugin-core"]
        elif isinstance(node.os, Fedora) or isinstance(node.os, Suse):
            vpp_packages.append("vpp-plugins")
        else:
            raise SkippedException(
                UnsupportedDistroException(
                    self.node.os, "VPP is not supported on this OS"
                )
            )

        node.os.install_packages(vpp_packages)
