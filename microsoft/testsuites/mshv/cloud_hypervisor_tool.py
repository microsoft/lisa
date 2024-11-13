# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import secrets
from pathlib import Path

from lisa import Node
from lisa.executable import Tool
from lisa.tools import Dmesg
from lisa.util.process import Process


class CloudHypervisor(Tool):
    @property
    def command(self) -> str:
        return "cloud-hypervisor"

    @property
    def can_install(self) -> bool:
        # cloud-hypervisor is already installed in MSHV dom0 image.
        return False

    def start_vm_async(
        self,
        kernel: str,
        cpus: int,
        memory_mb: int,
        disk_path: str,
        disk_readonly: bool = False,
        sudo: bool = False,
        guest_vm_type: str = "NON-CVM",
        igvm_path: str = "",
        log_file: str = "",
    ) -> Process:
        opt_disk_readonly = "on" if disk_readonly else "off"
        log_file_arg = f"--log-file {log_file}" if log_file else ""
        args: str = f'--cpus boot={cpus} --memory size={memory_mb}M --disk "path={disk_path},readonly={opt_disk_readonly}" {log_file_arg} --net "tap=,mac=,ip=,mask="'  # noqa: E501

        if guest_vm_type == "CVM":
            host_data = secrets.token_hex(32)
            args = f"{args} --platform sev_snp=on --host-data {host_data} --igvm {igvm_path}"  # noqa: E501
        else:
            args = f"{args} --kernel {kernel}"

        return self.run_async(
            args,
            force_run=True,
            shell=True,
            sudo=sudo,
        )

    def save_dmesg_logs(self, node: Node, log_path: Path) -> None:
        dmesg_str = node.tools[Dmesg].get_output()
        dmesg_path = log_path / "dmesg"
        with open(str(dmesg_path), "w", encoding="utf-8") as f:
            f.write(dmesg_str)
