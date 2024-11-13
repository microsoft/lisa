# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
import time
from dataclasses import dataclass, field
from typing import Dict, Optional

from assertpy import assert_that
from dataclasses_json import config, dataclass_json

from lisa.executable import Tool
from lisa.operating_system import Windows
from lisa.tools.powershell import PowerShell
from lisa.util import LisaException
from lisa.util.process import Process


@dataclass_json
@dataclass
class VMSwitch:
    name: str = field(metadata=config(field_name="Name"))


class HyperV(Tool):
    # 192.168.5.12
    IP_REGEX = r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}"

    @property
    def command(self) -> str:
        return ""

    @property
    def can_install(self) -> bool:
        return True

    def exists_vm(self, name: str) -> bool:
        output = self.node.tools[PowerShell].run_cmdlet(
            f"Get-VM -Name {name}",
            fail_on_error=False,
            force_run=True,
        )

        return output.strip() != ""

    def delete_vm_async(self, name: str) -> Optional[Process]:
        # check if vm is present
        if not self.exists_vm(name):
            return None

        # stop and delete vm
        self.stop_vm(name=name)
        powershell = self.node.tools[PowerShell]
        return powershell.run_cmdlet_async(
            f"Remove-VM -Name {name} -Force",
            force_run=True,
        )

    def delete_vm(self, name: str) -> None:
        process = self.delete_vm_async(name)

        if process is None:
            return

        process.wait_result(expected_exit_code=0)

    def create_vm(
        self,
        name: str,
        guest_image_path: str,
        switch_name: str,
        generation: int = 1,
        cores: int = 2,
        memory: int = 2048,
        attach_offline_disks: bool = True,
        com_ports: Optional[Dict[int, str]] = None,
        secure_boot: bool = True,
        stop_existing_vm: bool = True,
        extra_args: Optional[Dict[str, str]] = None,
    ) -> None:
        if stop_existing_vm:
            self.delete_vm(name)

        powershell = self.node.tools[PowerShell]

        # create a VM in hyperv
        self._run_hyperv_cmdlet(
            "New-VM",
            f'-Name "{name}" -Generation {generation} -MemoryStartupBytes {memory}MB '
            f'-BootDevice VHD -VHDPath "{guest_image_path}" '
            f'-SwitchName "{switch_name}"',
            extra_args=extra_args,
            force_run=True,
        )

        if extra_args is not None and "set-vmprocessor" in extra_args:
            self._run_hyperv_cmdlet(
                "Set-VMProcessor",
                f"-VMName {name}",
                extra_args=extra_args,
                force_run=True,
            )

        # set cores and memory type
        self._run_hyperv_cmdlet(
            "Set-VM",
            f"-Name {name} -ProcessorCount {cores} -StaticMemory "
            "-CheckpointType Disabled",
            extra_args=extra_args,
            force_run=True,
        )

        # disable secure boot if requested
        # secure boot is only supported for generation 2 VMs
        if not secure_boot and generation == 2:
            self._run_hyperv_cmdlet(
                "Set-VMFirmware",
                f"-VMName {name} -EnableSecureBoot Off",
                extra_args=extra_args,
                force_run=True,
            )

        # add disks if requested
        if attach_offline_disks:
            disk_info = powershell.run_cmdlet(
                "(Get-Disk | Where-Object {$_.OperationalStatus -eq 'offline'}).Number",
                force_run=True,
            )
            matched = re.findall(r"\d+", disk_info)
            disk_numbers = [int(x) for x in matched]
            for disk_number in disk_numbers:
                self._run_hyperv_cmdlet(
                    "Add-VMHardDiskDrive",
                    f"-VMName {name} -DiskNumber {disk_number} -ControllerType 'SCSI'",
                    extra_args=extra_args,
                    force_run=True,
                )

        # configure COM ports if specified
        if com_ports:
            for port_number, pipe_path in com_ports.items():
                # only port numbers 1 and 2 are supported
                # they correspond to COM1 and COM2 respectively
                if port_number != 1 and port_number != 2:
                    continue

                self._run_hyperv_cmdlet(
                    "Set-VMComPort",
                    f"-VMName {name} -Number {port_number} -Path {pipe_path}",
                    extra_args=extra_args,
                    force_run=True,
                )

    def start_vm(
        self,
        name: str,
        extra_args: Optional[Dict[str, str]] = None,
    ) -> None:
        # start vm
        self._run_hyperv_cmdlet(
            "Start-VM", f"-Name {name}", extra_args=extra_args, force_run=True
        )

        # wait for vm start
        timeout_start = time.time()
        is_ready = False
        self._log.debug(f"Waiting for VM {name} to start")
        while time.time() - timeout_start < 600:
            try:
                if self.get_ip_address(name):
                    self._log.debug(f"VM {name} is ready")
                    is_ready = True
                    break
            except LisaException as e:
                self._log.debug(f"VM {name} not ready: {e}")
                time.sleep(10)

        if not is_ready:
            raise LisaException(f"VM {name} did not start")

    def stop_vm(self, name: str) -> None:
        # stop vm
        self._run_hyperv_cmdlet("Stop-VM", f"-Name {name} -Force", force_run=True)

    def restart_vm(
        self,
        name: str,
    ) -> None:
        # restart vm
        self._run_hyperv_cmdlet("Restart-VM", f"-Name {name} -Force", force_run=True)

    def enable_device_passthrough(self, name: str, mmio_mb: int = 5120) -> None:
        self._run_hyperv_cmdlet(
            "Set-VM",
            f"-Name {name} -AutomaticStopAction TurnOff",
            force_run=True,
        )
        self._run_hyperv_cmdlet(
            "Set-VM",
            f"-HighMemoryMappedIoSpace {mmio_mb}Mb -VMName {name}",
            force_run=True,
        )

    def get_default_external_switch(self) -> Optional[VMSwitch]:
        switch_json = self.node.tools[PowerShell].run_cmdlet(
            'Get-VMSwitch | Where-Object {$_.SwitchType -eq "External"} '
            "| Select -First 1 | select Name | ConvertTo-Json",
            force_run=True,
        )

        if not switch_json:
            return None

        return VMSwitch.from_json(switch_json)  # type: ignore

    def exists_switch(self, name: str) -> bool:
        output = self.node.tools[PowerShell].run_cmdlet(
            f"Get-VMSwitch -Name {name}",
            fail_on_error=False,
            force_run=True,
        )
        return output.strip() != ""

    def delete_switch(self, name: str) -> None:
        if self.exists_switch(name):
            self.node.tools[PowerShell].run_cmdlet(
                f"Remove-VMSwitch -Name {name} -Force",
                force_run=True,
            )

    def create_switch(self, name: str) -> None:
        # remove switch if it exists
        self.delete_switch(name)

        # create a new switch
        self.node.tools[PowerShell].run_cmdlet(
            f"New-VMSwitch -Name {name} -SwitchType Internal",
            force_run=True,
        )

    def get_switch_interface_index(self, switch_name: str) -> int:
        output = self.node.tools[PowerShell].run_cmdlet(
            f"(Get-NetAdapter -Name '*{switch_name}*').ifindex",
            force_run=True,
        )
        return int(output.strip())

    def exists_nat(self, name: str) -> bool:
        output = self.node.tools[PowerShell].run_cmdlet(
            f"Get-NetNat -Name {name}",
            fail_on_error=False,
            force_run=True,
        )
        return output.strip() != ""

    def delete_nat(self, name: str) -> None:
        if self.exists_nat(name):
            self.node.tools[PowerShell].run_cmdlet(
                f"Remove-NetNat -Name {name} -Confirm:$false",
                force_run=True,
            )

    def create_nat(self, name: str, ip_range: str) -> None:
        # delete NAT if it exists
        self.delete_nat(name)

        # create a new NAT
        self.node.tools[PowerShell].run_cmdlet(
            f"New-NetNat -Name {name} -InternalIPInterfaceAddressPrefix '{ip_range}' ",
            force_run=True,
        )

    def delete_nat_networking(self, switch_name: str, nat_name: str) -> None:
        # Delete switch
        self.delete_switch(switch_name)

        # delete NAT
        self.delete_nat(nat_name)

    def setup_nat_networking(self, switch_name: str, nat_name: str) -> None:
        """
        Setup NAT networking
        Reference: https://docs.microsoft.com/en-us/virtualization/hyper-v-on-windows/user-guide/setup-nat-network # noqa
        """
        # create a new switch
        self.create_switch(switch_name)

        # find interface index of the switch
        interface_index = self.get_switch_interface_index(switch_name)

        # set switch interface as gateway for NAT
        self.node.tools[PowerShell].run_cmdlet(
            "New-NetIPAddress -IPAddress 192.168.5.1 "
            f"-InterfaceIndex {interface_index} -PrefixLength 24",
            force_run=True,
        )

        # create a new NAT
        self.create_nat(nat_name, "192.168.5.0/24")

    def get_ip_address(self, name: str) -> str:
        # verify vm is running
        assert_that(self.exists_vm(name)).is_true()

        # get vm ip address
        output = self.node.tools[PowerShell].run_cmdlet(
            f"Get-VM -Name {name} | Select -ExpandProperty networkadapters | select"
            " ipaddresses",
            force_run=True,
        )

        # regex match for ip address
        match = re.search(self.IP_REGEX, output)
        ip_address = match.group(0) if match else ""

        # raise exception if ip address is not found
        if not ip_address:
            raise LisaException(f"Could not find IP address for VM {name}")

        return ip_address

    def exist_port_forwarding(
        self,
        nat_name: str,
    ) -> bool:
        output = self.node.tools[PowerShell].run_cmdlet(
            f"Get-NetNatStaticMapping -NatName {nat_name}",
            fail_on_error=False,
            force_run=True,
        )
        return output.strip() != ""

    def delete_port_forwarding(self, nat_name: str) -> None:
        if self.exist_port_forwarding(nat_name):
            self.node.tools[PowerShell].run_cmdlet(
                f"Remove-NetNatStaticMapping -NatName {nat_name} -Confirm:$false",
                force_run=True,
            )

    def setup_port_forwarding(
        self,
        nat_name: str,
        host_port: int,
        guest_ip: str,
        host_ip: str = "0.0.0.0",
        guest_port: int = 22,
    ) -> None:
        # create new port forwarding
        self.node.tools[PowerShell].run_cmdlet(
            f"Add-NetNatStaticMapping -NatName {nat_name} "
            f"-ExternalIPAddress {host_ip} -ExternalPort {host_port} "
            f"-InternalIPAddress {guest_ip} -InternalPort {guest_port} -Protocol TCP",
            force_run=True,
        )

    def exists_virtual_disk(self, name: str) -> bool:
        output = self.node.tools[PowerShell].run_cmdlet(
            f"Get-VirtualDisk -FriendlyName {name}",
            fail_on_error=False,
            force_run=True,
        )
        return output.strip() != ""

    def delete_virtual_disk(self, name: str) -> None:
        if self.exists_virtual_disk(name):
            self.node.tools[PowerShell].run_cmdlet(
                f"Remove-VirtualDisk -FriendlyName {name} -confirm:$false",
                force_run=True,
            )

    def create_virtual_disk(self, name: str, pool_name: str, columns: int = 2) -> None:
        # remove existing virtual disk, if it exists
        self.delete_virtual_disk(name)

        # create a new virtual disk from `pool_name`
        self.node.tools[PowerShell].run_cmdlet(
            f"New-VirtualDisk -FriendlyName {name} "
            f"-StoragePoolFriendlyName {pool_name} -Interleave 65536 "
            f"-UseMaximumSize -NumberOfColumns {columns} "
            "-ResiliencySettingName Simple",
            force_run=True,
        )

    def _check_exists(self) -> bool:
        try:
            self.node.tools[PowerShell].run_cmdlet(
                "Get-VM",
                force_run=True,
            )
            self._log.debug("Hyper-V is installed")
            return True
        except LisaException as e:
            self._log.debug(f"Hyper-V not installed: {e}")
            return False

    def _install(self) -> bool:
        assert isinstance(self.node.os, Windows)

        # enable hyper-v
        self.node.tools[PowerShell].run_cmdlet(
            "Install-WindowsFeature -Name Hyper-V -IncludeManagementTools",
            force_run=True,
        )

        # reboot node
        self.node.reboot()

        return self._check_exists()

    def _run_hyperv_cmdlet(
        self,
        cmd: str,
        args: str,
        extra_args: Optional[Dict[str, str]] = None,
        force_run: bool = False,
    ) -> str:
        pwsh = self.node.tools[PowerShell]
        if not extra_args:
            extra_args = {}
        return pwsh.run_cmdlet(
            f"{cmd} {args} {extra_args.get(cmd.lower(), '')}", force_run=force_run
        )
