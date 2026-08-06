# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from unittest import TestCase
from unittest.mock import MagicMock

from lisa.microsoft.testsuites.mshv.cloud_hypervisor_tool import CloudHypervisor


class CloudHypervisorToolTestCase(TestCase):
    def _render_command(self, guest_vm_type: str) -> str:
        tool = CloudHypervisor.__new__(CloudHypervisor)
        tool.run_async = MagicMock(return_value=MagicMock())

        tool.start_vm_async(
            kernel="/kernel",
            cpus=2,
            memory_mb=1024,
            disk_path="/disk.img",
            sudo=True,
            guest_vm_type=guest_vm_type,
            igvm_path="/igvm",
            log_file="/vm.log",
        )

        return tool.run_async.call_args.args[0]

    def test_confidential_guest_types_disable_nested_virtualization(self) -> None:
        for guest_vm_type in ("CVM", "ConfidentialVM"):
            with self.subTest(guest_vm_type=guest_vm_type):
                command = self._render_command(guest_vm_type)

                self.assertIn("--cpus boot=2,nested=off", command)
                self.assertIn("--platform sev_snp=on", command)

    def test_non_cvm_launch_is_unchanged(self) -> None:
        command = self._render_command("NON-CVM")

        self.assertIn("--cpus boot=2 ", command)
        self.assertNotIn("nested=", command)
        self.assertIn("--kernel /kernel", command)
        self.assertNotIn("--platform sev_snp=on", command)
