# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from lisa.executable import Tool
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
    ) -> Process:
        opt_disk_readonly = "on" if disk_readonly else "off"
        return self.run_async(
            f'--kernel {kernel} --cpus boot={cpus} --memory size={memory_mb}M --disk "path={disk_path},readonly={opt_disk_readonly}" --net "tap=,mac=,ip=,mask="',  # noqa: E501
            force_run=True,
            shell=True,
        )
