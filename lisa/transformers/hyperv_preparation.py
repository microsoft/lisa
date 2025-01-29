from dataclasses import dataclass
from typing import Any, Dict, List, Type

from lisa import schema
from lisa.tools import HyperV, Sshpass
from lisa.transformers.deployment_transformer import (
    DeploymentTransformer,
    DeploymentTransformerSchema,
)


@dataclass
class HyperVPreparationTransformerSchema(DeploymentTransformerSchema):
    # source path of files to be uploaded
    guest_image_server_vhd_path: str = ""
    # destination path of files to be uploaded
    guest_image_local_vhd_path: str = ""
    guest_image_blob_url: str = ""


class HyperVPreparationTransformer(DeploymentTransformer):
    """
    This Transformer configures Windows Azure VM as a Hyper-V environment.
    """

    @classmethod
    def type_name(cls) -> str:
        return "hyperv_preparation"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return HyperVPreparationTransformerSchema

    @property
    def _output_names(self) -> List[str]:
        return []

    def _upload_blob_to_server(self) -> None:
        runbook: HyperVPreparationTransformerSchema = self.runbook
        assert isinstance(runbook, HyperVPreparationTransformerSchema)

        #AzureBlobOperator.download_blob(
        #    blob_url=runbook.guest_image_blob_url,
        #    destination_path=runbook.guest_image_blob_path,
        #)

        self._node.tools[Sshpass].copy(
            source_path=runbook.guest_image_server_vhd_path,
            target_path=runbook.guest_image_local_vhd_path,
            target_ip=runbook.connection.address,
            target_username=runbook.connection.username,
            target_password=runbook.connection.password,
            target_port=22,
        )

    def _internal_run(self) -> Dict[str, Any]:
        runbook: HyperVPreparationTransformerSchema = self.runbook
        assert isinstance(runbook, HyperVPreparationTransformerSchema)

        #if runbook.guest_image_blob_url:
        #    self._upload_blob_to_server()

        switch_name = "InternalNAT"

        # Enable Hyper-V
        hv = self._node.tools[HyperV]

        # Create an internal switch.
        hv.create_switch(name=switch_name)

        hv.setup_nat_networking(switch_name=switch_name, nat_name=switch_name)

        # Configure Internal DHCP
        hv.enable_internal_dhcp()
        return {}
