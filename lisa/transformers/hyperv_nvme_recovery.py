# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import base64
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Type, cast

from dataclasses_json import dataclass_json

from lisa import LisaException, RemoteNode, schema
from lisa.sut_orchestrator.hyperv.context import HyperVNvmeRecoveryState
from lisa.sut_orchestrator.hyperv.hyperv_device_pool import HyperVDevicePool
from lisa.sut_orchestrator.hyperv.schema import HypervPlatformSchema
from lisa.tools import PowerShell
from lisa.transformers.deployment_transformer import (
    DeploymentTransformer,
    DeploymentTransformerSchema,
)
from lisa.util import field_metadata


@dataclass_json
@dataclass
class HyperVNvmeRecoveryTransformerSchema(DeploymentTransformerSchema):
    action: str = field(default="", metadata=field_metadata(required=True))
    state_path: str = field(default="", metadata=field_metadata(required=True))
    location_path: str = ""
    vm_name: str = ""


class HyperVNvmeRecoveryTransformer(DeploymentTransformer):
    CAPTURE = "capture"
    RECOVER = "recover"
    LOCATION_PATH = "location_path"
    VM_NAME = "vm_name"

    @classmethod
    def type_name(cls) -> str:
        return "hyperv_nvme_recovery"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return HyperVNvmeRecoveryTransformerSchema

    @property
    def _output_names(self) -> List[str]:
        return [self.LOCATION_PATH, self.VM_NAME]

    def _internal_run(self) -> Dict[str, Any]:
        runbook = cast(HyperVNvmeRecoveryTransformerSchema, self.runbook)
        action = runbook.action.strip().lower()
        state_path = runbook.state_path.strip()
        if action not in {self.CAPTURE, self.RECOVER}:
            raise LisaException(
                "Hyper-V NVMe recovery action must be 'capture' or 'recover'"
            )
        if not state_path:
            raise LisaException("Hyper-V NVMe recovery state_path is required")

        pool = HyperVDevicePool(
            node=cast(RemoteNode, self._node),
            runbook=HypervPlatformSchema(),
            log=self._log,
        )
        state: HyperVNvmeRecoveryState
        vm_name = runbook.vm_name.strip()
        if action == self.CAPTURE:
            captured_state = pool.capture_nvme_recovery_state(runbook.location_path)
            existing_state = self._read_state(state_path, required=False)
            if existing_state:
                self._assert_same_identity(existing_state, captured_state)
                state = existing_state
            else:
                self._write_state(state_path, captured_state)
                state = captured_state
        else:
            loaded_state = self._read_state(state_path, required=True)
            if not loaded_state:
                raise LisaException(
                    f"Hyper-V NVMe recovery state at '{state_path}' is empty"
                )
            state = loaded_state
            vm_name = pool.recover_nvme_device(state, vm_name)

        return {self.LOCATION_PATH: state.location_path, self.VM_NAME: vm_name}

    def _read_state(
        self, state_path: str, required: bool
    ) -> Optional[HyperVNvmeRecoveryState]:
        escaped_state_path = state_path.replace("'", "''")
        required_value = "$true" if required else "$false"
        encoded_state = self._node.tools[PowerShell].run_cmdlet(
            cmdlet=f"""
$statePath = '{escaped_state_path}'
if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) {{
    if ({required_value}) {{
        throw "Hyper-V NVMe recovery state was not found at '$statePath'"
    }}
    return
}}
[Convert]::ToBase64String([IO.File]::ReadAllBytes($statePath))
""",
            force_run=True,
        )
        normalized_state = encoded_state.strip()
        if not normalized_state:
            return None
        try:
            state_json = base64.b64decode(normalized_state, validate=True).decode(
                "utf-8-sig"
            )
        except ValueError as err:
            raise LisaException(
                f"Invalid Hyper-V NVMe recovery state encoding at '{state_path}'"
            ) from err
        return HyperVNvmeRecoveryState.from_json(state_json)

    def _write_state(self, state_path: str, state: HyperVNvmeRecoveryState) -> None:
        escaped_state_path = state_path.replace("'", "''")
        encoded_state = base64.b64encode(state.to_json().encode("utf-8")).decode(
            "ascii"
        )
        self._node.tools[PowerShell].run_cmdlet(
            cmdlet=f"""
$statePath = [IO.Path]::GetFullPath('{escaped_state_path}')
$stateDirectory = [IO.Path]::GetDirectoryName($statePath)
if (-not (Test-Path -LiteralPath $stateDirectory -PathType Container)) {{
    New-Item `
        -ItemType Directory `
        -Path $stateDirectory `
        -Force `
        -ErrorAction Stop | Out-Null
}}
$temporaryStatePath = "$statePath.$([guid]::NewGuid().ToString('N')).tmp"
try {{
    $stateBytes = [Convert]::FromBase64String('{encoded_state}')
    [IO.File]::WriteAllBytes($temporaryStatePath, $stateBytes)
    Move-Item `
        -LiteralPath $temporaryStatePath `
        -Destination $statePath `
        -Force `
        -ErrorAction Stop
}}
finally {{
    Remove-Item `
        -LiteralPath $temporaryStatePath `
        -Force `
        -ErrorAction SilentlyContinue
}}
""",
            force_run=True,
        )

    def _assert_same_identity(
        self,
        expected: HyperVNvmeRecoveryState,
        actual: HyperVNvmeRecoveryState,
    ) -> None:
        identity_pairs = {
            "location_path": (expected.location_path, actual.location_path),
            "instance_id": (expected.instance_id, actual.instance_id),
            "unique_id": (expected.disk.unique_id, actual.disk.unique_id),
            "serial_number": (
                expected.disk.serial_number,
                actual.disk.serial_number,
            ),
        }
        for property_name, (expected_value, actual_value) in identity_pairs.items():
            if expected_value and expected_value.casefold() != actual_value.casefold():
                raise LisaException(
                    "Hyper-V NVMe recovery identity mismatch for " f"'{property_name}'"
                )
