# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, Dict, List, Type, cast

from azure.mgmt.compute.models import GrantAccessData  # type: ignore
from dataclasses_json import dataclass_json
from retry import retry

from lisa import schema
from lisa.environment import Environments, EnvironmentSpace
from lisa.features import StartStop
from lisa.node import Node, RemoteNode
from lisa.parameter_parser.runbook import RunbookBuilder
from lisa.platform_ import load_platform_from_builder
from lisa.transformer import Transformer
from lisa.util import (
    LisaException,
    constants,
    field_metadata,
    get_date_str,
    get_datetime_path,
)

from .common import (
    AZURE_SHARED_RG_NAME,
    check_or_create_storage_account,
    get_compute_client,
    get_environment_context,
    get_or_create_storage_container,
    get_primary_ip_addresses,
    get_storage_account_name,
    get_vm,
    load_environment,
    wait_copy_blob,
    wait_operation,
)
from .platform_ import AzurePlatform
from .tools import Waagent

DEFAULT_EXPORTED_VHD_CONTAINER_NAME = "lisa-vhd-exported"
DEFAULT_VHD_SUFFIX = "exported"


@retry(tries=10, jitter=(1, 2))
def _generate_vhd_path(container_client: Any, file_name_part: str = "") -> str:
    path = PurePosixPath(
        f"{get_date_str()}/{get_datetime_path()}_"
        f"{DEFAULT_VHD_SUFFIX}_{file_name_part}.vhd"
    )
    blobs = container_client.list_blobs(name_starts_with=path)
    for _ in blobs:
        raise LisaException(f"blob exists already: {path}")
    return str(path)


@dataclass_json
@dataclass
class VhdTransformerSchema(schema.Transformer):
    # shared resource group name
    shared_resource_group_name: str = AZURE_SHARED_RG_NAME
    # resource group and vm name to be exported
    resource_group_name: str = field(default="", metadata=field_metadata(required=True))
    vm_name: str = ""

    # values for SSH connection. public_address is optional, because it can be
    # retrieved from vm_name. Others can be retrieved from platform.
    public_address: str = ""
    public_port: int = 22
    username: str = constants.DEFAULT_USER_NAME
    password: str = ""
    private_key_file: str = ""

    # values for exported vhd. storage_account_name is optional, because it can
    # be the default storage of LISA.
    storage_account_name: str = ""
    container_name: str = DEFAULT_EXPORTED_VHD_CONTAINER_NAME
    file_name_part: str = ""
    # Users may want to export VHD with the name they defined. For example,
    # OpenLogic-CentOS-7.9-20221227.vhd, or OpenLogic/CentOS/7.9/20221227.vhd
    custom_blob_name: str = ""

    # restore environment or not
    restore: bool = False


@dataclass_json
@dataclass
class DeployTransformerSchema(schema.Transformer):
    requirement: schema.Capability = field(default_factory=schema.Capability)
    resource_group_name: str = ""


@dataclass_json
@dataclass
class DeleteTransformerSchema(schema.Transformer):
    resource_group_name: str = field(default="", metadata=field_metadata(required=True))


class VhdTransformer(Transformer):
    """
    convert an azure VM to VHD, which is ready to deploy.
    """

    __url_name = "url"

    @classmethod
    def type_name(cls) -> str:
        return "azure_vhd"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return VhdTransformerSchema

    @property
    def _output_names(self) -> List[str]:
        return [self.__url_name]

    def _internal_run(self) -> Dict[str, Any]:
        runbook: VhdTransformerSchema = self.runbook
        platform = _load_platform(self._runbook_builder, self.type_name())

        environment = load_environment(platform, runbook.resource_group_name, self._log)

        if runbook.vm_name:
            node = next(
                x for x in environment.nodes.list() if x.name == runbook.vm_name
            )
        else:
            # if no vm_name specified, use the first vm
            node = next(x for x in environment.nodes.list())

        assert isinstance(node, RemoteNode)

        self._prepare_virtual_machine(node)

        virtual_machine = get_vm(platform, node)

        vhd_location = self._export_vhd(platform, virtual_machine)

        self._restore_vm(platform, virtual_machine, node)

        return {self.__url_name: vhd_location}

    def _prepare_virtual_machine(self, node: RemoteNode) -> None:
        runbook: VhdTransformerSchema = self.runbook
        if not runbook.public_address:
            runbook.public_address = node.public_address

        # prepare vm for exporting
        wa = node.tools[Waagent]
        node.execute("export HISTSIZE=0", shell=True)
        wa.deprovision()

        # stop the vm
        startstop = node.features[StartStop]
        startstop.stop()

    def _export_vhd(self, platform: AzurePlatform, virtual_machine: Any) -> str:
        runbook: VhdTransformerSchema = self.runbook
        compute_client = get_compute_client(platform)

        # generate sas url from os disk, so it can be copied.
        self._log.debug("generating sas url...")
        location = virtual_machine.location
        os_disk_name = virtual_machine.storage_profile.os_disk.name
        operation = compute_client.disks.begin_grant_access(
            resource_group_name=runbook.resource_group_name,
            disk_name=os_disk_name,
            grant_access_data=GrantAccessData(access="Read", duration_in_seconds=86400),
        )
        wait_operation(operation)
        sas_url = operation.result().access_sas
        assert sas_url, "cannot get sas_url from os disk"

        self._log.debug("getting or creating storage account and container...")
        # get vhd container
        if not runbook.storage_account_name:
            runbook.storage_account_name = get_storage_account_name(
                subscription_id=platform.subscription_id, location=location, type_="t"
            )

        check_or_create_storage_account(
            credential=platform.credential,
            subscription_id=platform.subscription_id,
            account_name=runbook.storage_account_name,
            resource_group_name=runbook.shared_resource_group_name,
            location=location,
            log=self._log,
        )
        container_client = get_or_create_storage_container(
            credential=platform.credential,
            subscription_id=platform.subscription_id,
            account_name=runbook.storage_account_name,
            container_name=runbook.container_name,
            resource_group_name=runbook.shared_resource_group_name,
        )

        if runbook.custom_blob_name:
            path = runbook.custom_blob_name
        else:
            path = _generate_vhd_path(container_client, runbook.file_name_part)
        vhd_path = f"{container_client.url}/{path}"
        blob_client = container_client.get_blob_client(path)
        blob_client.start_copy_from_url(sas_url, metadata=None, incremental_copy=False)

        wait_copy_blob(blob_client, vhd_path, self._log)

        return vhd_path

    def _restore_vm(
        self, platform: AzurePlatform, virtual_machine: Any, node: Node
    ) -> None:
        runbook: VhdTransformerSchema = self.runbook

        self._log.debug("restoring vm...")
        # release the vhd export lock, so it can be started back
        compute_client = get_compute_client(platform)
        os_disk_name = virtual_machine.storage_profile.os_disk.name
        operation = compute_client.disks.begin_revoke_access(
            resource_group_name=runbook.resource_group_name,
            disk_name=os_disk_name,
        )
        wait_operation(operation)

        if runbook.restore:
            start_stop = node.features[StartStop]
            start_stop.start()

    def _get_public_ip_address(
        self, platform: AzurePlatform, virtual_machine: Any
    ) -> str:
        runbook: VhdTransformerSchema = self.runbook

        public_ip_address, _ = get_primary_ip_addresses(
            platform, runbook.resource_group_name, virtual_machine
        )
        assert (
            public_ip_address
        ), "cannot find public IP address, make sure the VM is in running status."

        return public_ip_address


class DeployTransformer(Transformer):
    """
    deploy a node in transformer phase for further operations
    """

    __resource_group_name = "resource_group_name"

    @classmethod
    def type_name(cls) -> str:
        return "azure_deploy"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return DeployTransformerSchema

    @property
    def _output_names(self) -> List[str]:
        return [
            self.__resource_group_name,
            constants.ENVIRONMENTS_NODES_REMOTE_ADDRESS,
            constants.ENVIRONMENTS_NODES_REMOTE_PORT,
            constants.ENVIRONMENTS_NODES_REMOTE_USERNAME,
            constants.ENVIRONMENTS_NODES_REMOTE_PASSWORD,
            constants.ENVIRONMENTS_NODES_REMOTE_PRIVATE_KEY_FILE,
        ]

    def _internal_run(self) -> Dict[str, Any]:
        platform = _load_platform(self._runbook_builder, self.type_name())
        runbook: DeployTransformerSchema = self.runbook

        envs = Environments()
        environment_requirement = EnvironmentSpace()
        environment_requirement.nodes.append(runbook.requirement)
        environment = envs.from_requirement(environment_requirement)
        assert environment

        platform.prepare_environment(environment=environment)

        platform.deploy_environment(environment)

        resource_group_name = get_environment_context(environment).resource_group_name

        # generate return results
        results = {
            self.__resource_group_name: resource_group_name,
        }
        node: RemoteNode = cast(RemoteNode, environment.default_node)
        connection_info = node.connection_info
        assert connection_info
        results.update(connection_info)
        return results


class DeleteTransformer(Transformer):
    """
    delete an environment
    """

    @classmethod
    def type_name(cls) -> str:
        return "azure_delete"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return DeleteTransformerSchema

    @property
    def _output_names(self) -> List[str]:
        return []

    def _internal_run(self) -> Dict[str, Any]:
        platform = _load_platform(self._runbook_builder, self.type_name())
        runbook: DeleteTransformerSchema = self.runbook

        # mock up environment for deletion
        envs = Environments()
        environment_requirement = EnvironmentSpace()
        environment_requirement.nodes.append(schema.NodeSpace())
        environment = envs.from_requirement(environment_requirement)
        assert environment
        environment_context = get_environment_context(environment)
        environment_context.resource_group_name = runbook.resource_group_name
        environment_context.resource_group_is_specified = True

        platform.delete_environment(environment)

        return {}


def _load_platform(
    runbook_builder: RunbookBuilder, transformer_name: str
) -> AzurePlatform:
    platform = load_platform_from_builder(runbook_builder)
    assert isinstance(
        platform, AzurePlatform
    ), f"'{transformer_name}' support only Azure platform"

    platform.initialize()
    return platform
