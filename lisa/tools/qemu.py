# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from assertpy.assertpy import assert_that

from lisa.executable import Tool
from lisa.operating_system import Fedora, Posix
from lisa.tools import Lsmod


class Qemu(Tool):

    QEMU_INSTALL_LOCATIONS = ["qemu-system-x86_64", "qemu-kvm", "/usr/libexec/qemu-kvm"]
    COMMAND = "qemu-system-x86_64"

    @property
    def command(self) -> str:
        return self.COMMAND

    def can_install(self) -> bool:
        return True

    def _install(self) -> bool:
        assert isinstance(self.node.os, Posix)

        # install qemu
        self.node.os.install_packages("qemu-kvm")

        # verify that kvm is enabled
        self._is_kvm_successfully_enabled()

        # find correct command for qemu
        for location in self.QEMU_INSTALL_LOCATIONS:
            self.COMMAND = location
            if self._check_exists():
                return True

        return False

    def _is_kvm_successfully_enabled(self) -> None:
        # verify that kvm module is loaded
        lsmod_output = self.node.tools[Lsmod].run().stdout
        is_kvm_successfully_enabled = (
            "kvm_intel" in lsmod_output or "kvm_amd" in lsmod_output
        )
        assert_that(
            is_kvm_successfully_enabled, f"KVM could not be enabled : {lsmod_output}"
        ).is_true()

    def create_nested_vm(
        self,
        port: int,
        guest_image_path: str,
    ) -> None:
        # start nested vm
        result = self.run(
            f"-smp 2 -m 2048 -hda {guest_image_path} "
            "-device e1000,netdev=user.0 "
            f"-netdev user,id=user.0,hostfwd=tcp::{port}-:22 "
            "-enable-kvm -display none -daemonize",
            sudo=True,
            shell=True,
        )
        assert_that(
            result.exit_code, f"Unable to start nested vm : {result}"
        ).is_equal_to(0)

        # update firewall rules
        # https://access.redhat.com/documentation/en-us/red_hat_enterprise_linux/8/html/configuring_and_managing_networking/using-and-configuring-firewalld_configuring-and-managing-networking # noqa E501
        if isinstance(self.node.os, Fedora):
            self.node.execute(
                f"firewall-cmd --permanent --add-port={port}/tcp", sudo=True
            )
            self.node.execute("firewall-cmd --reload", sudo=True)
