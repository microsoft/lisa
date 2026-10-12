# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import base64
import json
from types import SimpleNamespace
from typing import cast
from unittest import TestCase
from unittest.mock import MagicMock, patch

from lisa import LisaException
from lisa.node import Node
from lisa.sut_orchestrator.hyperv.context import HyperVNvmeRecoveryState, NvmeDiskState
from lisa.tools import PowerShell
from lisa.transformers.hyperv_nvme_recovery import (
    HyperVNvmeRecoveryTransformer,
    HyperVNvmeRecoveryTransformerSchema,
)


class HyperVNvmeRecoveryTransformerTestCase(TestCase):
    def setUp(self) -> None:
        self.state = HyperVNvmeRecoveryState(
            schema_version=1,
            location_path="PCIROOT(1)#PCI(0000)",
            instance_id="PCI\\VEN_144D&DEV_A80A",
            disk=NvmeDiskState(
                number=3,
                unique_id="disk-unique-id",
                serial_number="disk-serial",
                was_offline=False,
            ),
        )

    @patch(
        "lisa.transformers.hyperv_nvme_recovery.HyperVDevicePool."
        "capture_nvme_recovery_state"
    )
    def test_capture_writes_state_atomically(self, capture_state: MagicMock) -> None:
        capture_state.return_value = self.state
        powershell = MagicMock()
        powershell.run_cmdlet.side_effect = ["", ""]
        transformer = self._create_transformer("capture", powershell)

        result = transformer._internal_run()

        self.assertEqual(self.state.location_path, result["location_path"])
        write_command = powershell.run_cmdlet.call_args_list[1].kwargs["cmdlet"]
        self.assertIn("WriteAllBytes", write_command)
        self.assertIn("Move-Item", write_command)
        self.assertIn("finally", write_command)

    @patch("lisa.transformers.hyperv_nvme_recovery.HyperVDevicePool")
    def test_recover_reads_state_and_calls_pool(self, pool_type: MagicMock) -> None:
        encoded_state = base64.b64encode(self.state.to_json().encode()).decode()
        powershell = MagicMock()
        powershell.run_cmdlet.return_value = encoded_state
        transformer = self._create_transformer("recover", powershell)

        result = transformer._internal_run()

        pool_type.return_value.recover_nvme_device.assert_called_once_with(
            self.state, "vm1"
        )
        self.assertEqual(self.state.location_path, result["location_path"])

    @patch("lisa.transformers.hyperv_nvme_recovery.HyperVDevicePool")
    def test_recover_rejects_incomplete_state_before_pool_call(
        self, pool_type: MagicMock
    ) -> None:
        incomplete_state = base64.b64encode(
            json.dumps({"schema_version": 1}).encode()
        ).decode()
        powershell = MagicMock()
        powershell.run_cmdlet.return_value = incomplete_state
        transformer = self._create_transformer("recover", powershell)

        with self.assertRaisesRegex(LisaException, "properties do not match schema"):
            transformer._internal_run()

        pool_type.return_value.recover_nvme_device.assert_not_called()

    @patch(
        "lisa.transformers.hyperv_nvme_recovery.HyperVDevicePool."
        "capture_nvme_recovery_state"
    )
    def test_capture_rejects_existing_different_identity(
        self, capture_state: MagicMock
    ) -> None:
        capture_state.return_value = self.state
        different_state = HyperVNvmeRecoveryState(
            schema_version=1,
            location_path=self.state.location_path,
            instance_id="PCI\\DIFFERENT",
            disk=self.state.disk,
        )
        encoded_state = base64.b64encode(different_state.to_json().encode()).decode()
        powershell = MagicMock()
        powershell.run_cmdlet.return_value = encoded_state
        transformer = self._create_transformer("capture", powershell)

        with self.assertRaisesRegex(LisaException, "instance_id"):
            transformer._internal_run()

        self.assertEqual(1, powershell.run_cmdlet.call_count)

    @patch(
        "lisa.transformers.hyperv_nvme_recovery.HyperVDevicePool."
        "capture_nvme_recovery_state"
    )
    def test_capture_preserves_existing_same_identity_state(
        self, capture_state: MagicMock
    ) -> None:
        capture_state.return_value = self.state
        saved_state = HyperVNvmeRecoveryState(
            schema_version=1,
            location_path=self.state.location_path.lower(),
            instance_id=self.state.instance_id.lower(),
            disk=NvmeDiskState(
                number=self.state.disk.number,
                unique_id=self.state.disk.unique_id.upper(),
                serial_number=self.state.disk.serial_number.upper(),
                was_offline=True,
            ),
        )
        encoded_state = base64.b64encode(saved_state.to_json().encode()).decode()
        powershell = MagicMock()
        powershell.run_cmdlet.return_value = encoded_state
        transformer = self._create_transformer("capture", powershell)

        result = transformer._internal_run()

        self.assertEqual(saved_state.location_path, result["location_path"])
        self.assertEqual(1, powershell.run_cmdlet.call_count)

    @patch(
        "lisa.transformers.hyperv_nvme_recovery.HyperVDevicePool."
        "capture_nvme_recovery_state"
    )
    def test_unsafe_capture_does_not_write_state(
        self, capture_state: MagicMock
    ) -> None:
        capture_state.side_effect = LisaException("unsafe Windows disk")
        powershell = MagicMock()
        transformer = self._create_transformer("capture", powershell)

        with self.assertRaisesRegex(LisaException, "unsafe Windows disk"):
            transformer._internal_run()

        powershell.run_cmdlet.assert_not_called()

    def _create_transformer(
        self, action: str, powershell: MagicMock
    ) -> HyperVNvmeRecoveryTransformer:
        node = cast(Node, SimpleNamespace(tools={PowerShell: powershell}))
        runbook = HyperVNvmeRecoveryTransformerSchema(
            name="nvme_recovery",
            action=action,
            state_path="C:\\lisa\\nvme-recovery.json",
            vm_name="vm1",
        )
        return HyperVNvmeRecoveryTransformer(
            runbook=runbook,
            runbook_builder=MagicMock(),
            node=node,
            parent_logger=MagicMock(),
        )
