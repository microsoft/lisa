# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from dataclasses import dataclass, field
from typing import Any, Dict, List, Type, cast

from dataclasses_json import dataclass_json

from lisa import LisaException, RemoteNode, schema
from lisa.sut_orchestrator.hyperv.hyperv_device_pool import HyperVDevicePool
from lisa.sut_orchestrator.hyperv.schema import HypervPlatformSchema
from lisa.transformers.deployment_transformer import (
    DeploymentTransformer,
    DeploymentTransformerSchema,
)
from lisa.util import field_metadata


@dataclass_json
@dataclass
class HyperVNvmeRecoveryTransformerSchema(DeploymentTransformerSchema):
    state_path: str = field(default="", metadata=field_metadata(required=True))
    vm_name: str = ""


class HyperVNvmeRecoveryTransformer(DeploymentTransformer):
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
        state_path = runbook.state_path.strip()
        if not state_path:
            raise LisaException("Hyper-V NVMe recovery state_path is required")

        pool = HyperVDevicePool(
            node=cast(RemoteNode, self._node),
            runbook=HypervPlatformSchema(),
            log=self._log,
        )
        state = pool.read_nvme_recovery_state(state_path)
        if not state:
            raise LisaException(
                f"Hyper-V NVMe recovery state at '{state_path}' is empty"
            )
        vm_name = pool.recover_nvme_device(state, runbook.vm_name.strip())

        return {self.LOCATION_PATH: state.location_path, self.VM_NAME: vm_name}
