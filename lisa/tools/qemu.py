# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
import time
from typing import Any, List, Optional

from assertpy.assertpy import assert_that
from randmac import RandMac  # type: ignore

from lisa.executable import Tool
from lisa.operating_system import Fedora, Posix, Redhat
from lisa.tools import Ip, Kill, Lscpu, Lsmod, Pgrep
from lisa.tools.lscpu import CpuType
from lisa.util import LisaException, SkippedException, get_matched_str


class Qemu(Tool):
    QEMU_INSTALL_LOCATIONS = ["qemu-system-x86_64", "qemu-kvm", "/usr/libexec/qemu-kvm"]
    # qemu-kvm: unrecognized feature pcid
    NO_PCID_PATTERN = re.compile(r".*unrecognized feature pcid", re.M)
    # KVM: entry failed, hardware error 0xffffffff
    ERROR_WHEN_USE_HOST_CPU = re.compile(
        r"KVM: entry failed, hardware error 0xffffffff", re.M
    )

    @property
    def command(self) -> str:
        return self._qemu_command

    @property
    def can_install(self) -> bool:
        return True

    def create_vm(
        self,
        port: int,
        guest_image_path: str,
        cores: int = 2,
        memory: int = 4096,
        nic_model: str = "e1000",
        taps: int = 0,
        bridge: Optional[str] = None,
        disks: Optional[List[str]] = None,
        cd_rom: Optional[str] = None,
        stop_existing_vm: bool = True,
    ) -> None:
        """
        start vm on the current node

        arguments:
        port: port of the host vm mapped to the guest's ssh port
        guest_image_path: path of the guest image
        cores: number of cores of the vm. Defaults to 2
        memory: memory of the vm in MB. Defaults to 2048MB
        nics: number of qemu managed nics of the vm. Defaults to 1
        nic_model: model of the nics. Can be `e1000` or `virtio-net-pci`.
                    Defaults to `e1000` as it works with most x86 machines
        taps: number of taps interface to create. Defaults to 0
        bridge: bridge to use for attaching created taps. Defaults to None
        disks: list of data disks to attach to the vm. Defaults to None
        stop_existing_vm: stop existing vm if it is running. Defaults to True
        """

        # store name of tap interfaces added to the vm
        added_taps: List[str] = []

        # Run qemu with following parameters:
        # -m: memory size
        # -smp: SMP system with `n` CPUs
        # -hda : guest image path
        cmd = "-cpu host"

        # temp workaround for below issue
        # https://canonical.force.com/ua/s/case/5004K00000TILuWQAX/qemu-fails-to-boot-up-vm-on-the-azure-amd-instance-with-ubuntu-1804 # noqa: E501
        # The cause of the fairly to init is due to the `pcid` flag.
        # This works fine on intel procs, but fails to pass through successfully on amd
        if CpuType.AMD == self.node.tools[Lscpu].get_cpu_type():
            # for some qemu version, it doesn't support pcid flag
            # e.g. QEMU emulator version 1.5.3 (qemu-kvm-1.5.3-175.el7_9.6)
            # on centos 7.9
            # use a timeout mechanism to prevent the command from waiting the full 600
            # seconds before exiting.
            try_pcid_flag = self.node.execute(
                f"timeout 20 {self._qemu_command} -cpu host,pcid=no", sudo=True
            )
            if not get_matched_str(try_pcid_flag.stdout, self.NO_PCID_PATTERN):
                cmd += ",pcid=no"
        cmd += f" -smp {cores} -m {memory} -hda {guest_image_path} "

        # Add qemu managed nic device
        # This will be used to communicate with ssh to the guest
        # https://wiki.qemu.org/Documentation/Networking
        random_mac_address = str(RandMac())
        cmd += f"-device {nic_model},netdev=net0," f"mac={random_mac_address} "
        cmd += f"-netdev user,id=net0,hostfwd=tcp::{port}-:22 "

        # Add taps-based nic interfaces
        # Qemu automatically creates a tap interface `tap_<index>`
        if taps:
            for _ in range(taps):
                random_mac_address = str(RandMac())
                cmd += (
                    f"-device {nic_model},netdev=nettap{self.interface_count},"
                    f"mac={random_mac_address} "
                )
                cmd += (
                    f"-netdev tap,id=nettap{self.interface_count},vhost=on,script=no "
                )
                added_taps.append(f"tap{self.interface_count}")
                self.interface_count += 1

        # Add data disks
        if disks:
            for i, disk in enumerate(disks):
                cmd += (
                    f"-drive id=datadisk-{i},"
                    f"file={disk},cache=none,if=none,format=raw,aio=threads "
                    f"-device virtio-scsi-pci -device scsi-hd,drive=datadisk-{i} "
                )

        if cd_rom:
            cmd += f" -cdrom {cd_rom} "

        # kill any existing qemu process if stop_existing_vm is True
        if stop_existing_vm:
            self.delete_vm()

        cmd = self._configure_qemu_command_for_cpu(cmd)

        # -enable-kvm: enable kvm
        # -display: enable or disable display
        # -daemonize: run in background
        cmd += "-enable-kvm -display none -daemonize "

        result = self.run(
            cmd,
            sudo=True,
            shell=True,
        )
        if result.exit_code != 0:
            if "ret == cpu->kvm_msr_buf->nmsrs" in result.stdout:
                # Known issue with qemu on AMD
                # https://bugs.launchpad.net/qemu/+bug/1661386
                raise LisaException(
                    "Unable to start VM. "
                    "Found `ret == cpu->kvm_msr_buf->nmsrs` in stdout. "
                    "Known issue with qemu on AMD on older kernels"
                )
            elif "Cannot allocate memory" in result.stdout:
                raise SkippedException(
                    f"Not enough memory to start VM: {result.stdout}"
                )
            result.assert_exit_code(message=f"Unable to start VM {guest_image_path}")

        # if bridge is specified, attach the created taps to the bridge
        if bridge:
            for tap in added_taps:
                self.node.tools[Ip].up(tap)
                self.node.tools[Ip].set_master(tap, bridge)

        # update firewall rules
        # https://access.redhat.com/documentation/en-us/red_hat_enterprise_linux/8/html/configuring_and_managing_networking/using-and-configuring-firewalld_configuring-and-managing-networking # noqa E501
        if isinstance(self.node.os, Fedora):
            self.node.execute(
                f"firewall-cmd --permanent --add-port={port}/tcp", sudo=True
            )
            self.node.execute("firewall-cmd --reload", sudo=True)

    def delete_vm(self, timeout: int = 300) -> None:
        # stop vm
        kill = self.node.tools[Kill]
        qemu_processes = self.node.tools[Pgrep].get_processes("qemu")
        for process in qemu_processes:
            kill.by_pid(process.id)

        # `Qemu` is not stopped immediately after `kill` is called.
        # Wait until we find no running qemu processes.
        start_time = time.time()
        while time.time() - start_time < timeout:
            is_qemu_running = len(self.node.tools[Pgrep].get_processes("qemu")) > 0
            if not is_qemu_running:
                return

        raise LisaException("Unable to stop qemu after {} seconds".format(timeout))

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        self._qemu_command = "qemu-system-x86_64"
        self.interface_count = 0

    def _install(self) -> bool:
        assert isinstance(self.node.os, Posix)

        # install qemu
        self.node.os.install_packages("qemu-kvm")

        if isinstance(self.node.os, Redhat):
            # fix issue 'qemu-kvm: cannot initialize crypto: Unable to initialize gcrypt' # noqa E501
            self.node.os.install_packages("libgcrypt")

        # verify that kvm is enabled
        self._is_kvm_successfully_enabled()

        # find correct command for qemu
        for location in self.QEMU_INSTALL_LOCATIONS:
            self._qemu_command = location
            if self._check_exists():
                return True

        return False

    def _is_kvm_successfully_enabled(self) -> None:
        # verify that kvm module is loaded
        lsmod = self.node.tools[Lsmod]
        is_kvm_successfully_enabled = lsmod.module_exists(
            "kvm_intel"
        ) or lsmod.module_exists("kvm_amd")
        assert_that(is_kvm_successfully_enabled, "KVM could not be enabled").is_true()

    def _configure_qemu_command_for_cpu(self, cmd: str) -> str:
        # start qemu
        result = self.node.execute(
            f"timeout 20 {self.command} {cmd}",
            sudo=True,
            shell=True,
        )

        # using `-cpu host` is causing the issue
        # using `-cpu EPYC` for AMD CPU works correctly
        # if meet the failure pattern, use EPYC instead
        if get_matched_str(result.stdout, self.ERROR_WHEN_USE_HOST_CPU):
            cmd = cmd.replace("-cpu host", "-cpu EPYC")
        return cmd
