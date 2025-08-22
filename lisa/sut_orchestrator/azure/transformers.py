# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, Dict, List, Optional, Type, Union, cast

from azure.mgmt.compute.models import GrantAccessData
from dataclasses_json import dataclass_json
from marshmallow import validate
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
    check_blob_exist,
    check_or_create_gallery,
    check_or_create_gallery_image,
    check_or_create_gallery_image_version,
    check_or_create_resource_group,
    check_or_create_storage_account,
    copy_vhd_using_azcopy,
    generate_user_delegation_sas_token,
    get_compute_client,
    get_deployable_vhd_path,
    get_environment_context,
    get_or_create_storage_container,
    get_primary_ip_addresses,
    get_storage_account_name,
    get_vhd_details,
    get_vm,
    load_environment,
    wait_copy_blob,
    wait_operation,
)
from .platform_ import AzurePlatform, AzurePlatformSchema
from .tools import Waagent

DEFAULT_EXPORTED_VHD_CONTAINER_NAME = "lisa-vhd-exported"
DEFAULT_VHD_SUFFIX = "exported"


@retry(tries=10, jitter=(1, 2))  # type: ignore
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

    # deprovision the VM or not
    deprovision: bool = True

    # the AzCopy path can be specified if use this tool to copy blob
    azcopy_path: str = ""


@dataclass_json
@dataclass
class DeployTransformerSchema(schema.Transformer):
    requirement: schema.Capability = field(default_factory=schema.Capability)
    resource_group_name: str = ""
    deploy: bool = True
    source_address_prefixes: Optional[Union[str, List[str]]] = field(default=None)


@dataclass_json
@dataclass
class DeleteTransformerSchema(schema.Transformer):
    resource_group_name: str = field(default="", metadata=field_metadata(required=True))
    keep_environment: Optional[Union[str, bool]] = constants.ENVIRONMENT_KEEP_NO
    wait_delete: bool = False


class VhdTransformer(Transformer):
    """
    convert an azure VM to VHD, which is ready to deploy.
    """

    __url_name = "url"
    __vmgs_url_name = "vmgs_url"

    @classmethod
    def type_name(cls) -> str:
        return "azure_vhd"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return VhdTransformerSchema

    @property
    def _output_names(self) -> List[str]:
        return [self.__url_name, self.__vmgs_url_name]

    def _internal_run(self) -> Dict[str, Any]:
        runbook: VhdTransformerSchema = self.runbook
        platform = _load_platform(self._runbook_builder, self.type_name())
        azure_runbook: AzurePlatformSchema = self.runbook.get_extended_runbook(
            AzurePlatformSchema
        )

        environment = load_environment(
            platform,
            runbook.resource_group_name,
            azure_runbook.use_public_address,
            self._log,
        )

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

        outputs = self._export_vhd(platform, virtual_machine)

        self._restore_vm(platform, virtual_machine, node)

        return outputs

    def _prepare_virtual_machine(self, node: RemoteNode) -> None:
        runbook: VhdTransformerSchema = self.runbook
        if not runbook.public_address:
            runbook.public_address = node.public_address

        if runbook.deprovision:
            # prepare vm for exporting
            wa = node.tools[Waagent]
            node.execute("export HISTSIZE=0", shell=True)
            wa.deprovision()

        # stop the vm
        startstop = node.features[StartStop]
        startstop.stop()

    def _export_vhd(
        self, platform: AzurePlatform, virtual_machine: Any
    ) -> Dict[str, str]:
        runbook: VhdTransformerSchema = self.runbook
        compute_client = get_compute_client(platform)

        # generate sas url from os disk, so it can be copied.
        self._log.debug("generating sas url...")
        location = virtual_machine.location
        os_disk_name = virtual_machine.storage_profile.os_disk.name

        has_vmgs = (
            virtual_machine.storage_profile.os_disk.managed_disk.security_profile
            is not None
        )

        operation = compute_client.disks.begin_grant_access(
            resource_group_name=runbook.resource_group_name,
            disk_name=os_disk_name,
            grant_access_data=GrantAccessData(
                access="Read",
                duration_in_seconds=86400,
                get_secure_vm_guest_state_sas=has_vmgs,
            ),
        )
        wait_operation(operation)
        result = operation.result()
        sas_url = result.access_sas
        vmgs_sas_url = result.security_data_access_sas or ""
        assert sas_url, "cannot get sas_url from os disk"
        assert isinstance(sas_url, str), "sas_url is not a string"
        assert isinstance(vmgs_sas_url, str), "vmgs_sas_url is not a string"

        self._log.debug("getting or creating storage account and container...")
        # get vhd container
        if not runbook.storage_account_name:
            runbook.storage_account_name = get_storage_account_name(
                subscription_id=platform.subscription_id, location=location, type_="t"
            )

        check_or_create_storage_account(
            credential=platform.credential,
            subscription_id=platform.subscription_id,
            cloud=platform.cloud,
            account_name=runbook.storage_account_name,
            resource_group_name=runbook.shared_resource_group_name,
            location=location,
            log=self._log,
        )
        container_client = get_or_create_storage_container(
            credential=platform.credential,
            cloud=platform.cloud,
            account_name=runbook.storage_account_name,
            container_name=runbook.container_name,
            platform=platform,
        )

        if runbook.custom_blob_name:
            vhd_path = runbook.custom_blob_name
        else:
            vhd_path = _generate_vhd_path(container_client, runbook.file_name_part)
        vhd_url_path = f"{container_client.url}/{vhd_path}"
        vhd_blob_client = container_client.get_blob_client(vhd_path)
        if runbook.azcopy_path:
            sas_token = generate_user_delegation_sas_token(
                container_name=vhd_blob_client.container_name,
                blob_name=vhd_blob_client.blob_name,
                credential=platform.credential,
                cloud=platform.cloud,
                account_name=runbook.storage_account_name,
                writable=True,
                platform=platform,
            )
            dst_vhd_sas_url = f"{vhd_url_path}?{sas_token}"
            self._log.info(f"Copying VHD using AzCopy: {vhd_path}")
            copy_vhd_using_azcopy(
                azcopy_path=runbook.azcopy_path,
                src_vhd_sas_url=sas_url,
                dst_vhd_sas_url=dst_vhd_sas_url,
                blob_client=vhd_blob_client,
                log=self._log,
            )
        else:
            vhd_blob_client.start_copy_from_url(
                sas_url, metadata=None, incremental_copy=False
            )

        if vmgs_sas_url:
            vmgs_path = vhd_path.replace(".vhd", "_vmgs.vhd")
            assert vmgs_path != vhd_path, (
                "vmgs url path is the same as vhd url path. "
                "Make sure the custom_blob_name ends in .vhd"
            )
            vmgs_url_path = f"{container_client.url}/{vmgs_path}"
            vmgs_blob_client = container_client.get_blob_client(vmgs_path)
            if runbook.azcopy_path:
                sas_token = generate_user_delegation_sas_token(
                    container_name=vmgs_blob_client.container_name,
                    blob_name=vmgs_blob_client.blob_name,
                    credential=platform.credential,
                    cloud=platform.cloud,
                    account_name=runbook.storage_account_name,
                    writable=True,
                    platform=platform,
                )
                dst_vhd_sas_url = f"{vmgs_url_path}?{sas_token}"
                self._log.info(f"Copying VHD using AzCopy: {vmgs_path}")
                copy_vhd_using_azcopy(
                    azcopy_path=runbook.azcopy_path,
                    src_vhd_sas_url=vmgs_sas_url,
                    dst_vhd_sas_url=dst_vhd_sas_url,
                    blob_client=vmgs_blob_client,
                    log=self._log,
                )
            else:
                vmgs_blob_client.start_copy_from_url(
                    vmgs_sas_url, metadata=None, incremental_copy=False
                )
            wait_copy_blob(vmgs_blob_client, vmgs_url_path, self._log)
        else:
            vmgs_url_path = ""

        # Wait for VHD to copy after copying VMGS
        # so they can copy in parallel
        wait_copy_blob(vhd_blob_client, vhd_url_path, self._log)

        return {self.__url_name: vhd_url_path, self.__vmgs_url_name: vmgs_url_path}

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

        return public_ip_address  # type: ignore


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
        platform._azure_runbook.deploy = runbook.deploy
        if runbook.resource_group_name:
            platform._azure_runbook.resource_group_name = runbook.resource_group_name
        if runbook.source_address_prefixes:
            platform._azure_runbook.source_address_prefixes = (
                runbook.source_address_prefixes
            )
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

        platform.runbook.keep_environment = runbook.keep_environment
        platform._azure_runbook.wait_delete = runbook.wait_delete
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


@dataclass_json
@dataclass
class SigTransformerSchema(schema.Transformer):
    """
    transformer:
        - type: azure_sig
            vhd: "https://sc.blob.core.windows.net/vhds/pageblob.vhd"
            gallery_resource_group_name: rg_name
            gallery_name: galleryname
            gallery_image_location:
              - westus3
              - westus2
            gallery_image_hyperv_generation: 2
            gallery_image_name: image_name
            gallery_image_architecture: Arm64
            gallery_image_fullname: Microsoft Linux arm64 0.0.1
            rename:
              azure_sig_url: shared_gallery
    """

    # raw vhd URL, it can be the blob under the same subscription of SIG
    # or SASURL
    vhd: str = field(default="", metadata=field_metadata(required=True))
    # if not specify gallery_resource_group_name, use shared resource group name
    gallery_resource_group_name: str = field(default=AZURE_SHARED_RG_NAME)
    # if not specified, will use the first location of gallery image
    gallery_resource_group_location: str = field(default="")
    # gallery name, it can be reused if this gallery exists
    gallery_name: str = field(default="lisa_default_gallery")
    # if not specified, will use the first location of gallery image
    gallery_location: str = field(default="")
    gallery_description: str = field(default="SIG created from lisa transformers.")
    # gallery image location list
    # gallery_image_location:
    #   - westus3
    #   - westus2
    gallery_image_location: List[str] = field(
        default_factory=list, metadata=field_metadata(required=True)
    )
    # gallery image name, it can be reused if this gallery exists
    gallery_image_name: str = field(default="", metadata=field_metadata(required=True))
    # os type, can be Linux or Windows
    gallery_image_ostype: str = field(
        default="Linux",
        metadata=field_metadata(
            validate=validate.OneOf(
                [
                    "Windows",
                    "Linux",
                ]
            ),
        ),
    )
    # image security type, can be empty, TrustedLaunch
    gallery_image_securitytype: str = ""
    gallery_image_osstate: str = field(
        default="Generalized",
        metadata=field_metadata(
            validate=validate.OneOf(
                [
                    "Specialized",
                    "Generalized",
                ]
            ),
        ),
    )
    gallery_image_architecture: str = field(
        default="x64",
        metadata=field_metadata(
            validate=validate.OneOf(
                [
                    "x64",
                    "Arm64",
                ]
            ),
        ),
    )
    # image full name
    # format is publisher offer sku version
    gallery_image_fullname: str = field(
        default="", metadata=field_metadata(required=True)
    )
    gallery_image_hyperv_generation: int = field(
        default=1,
        metadata=field_metadata(
            validate=validate.OneOf([1, 2]),
        ),
    )
    regional_replica_count: int = 1
    storage_account_type: str = field(
        default="Standard_LRS",
        metadata=field_metadata(
            validate=validate.OneOf(
                [
                    "Premium_LRS",
                    "Standard_ZRS",
                    "Standard_LRS",
                ]
            ),
        ),
    )
    host_caching_type: str = field(
        default=constants.DATADISK_CACHING_TYPE_NONE,
        metadata=field_metadata(
            validate=validate.OneOf(
                [
                    constants.DATADISK_CACHING_TYPE_NONE,
                    constants.DATADISK_CACHING_TYPE_READONLY,
                    constants.DATADISK_CACHING_TYPE_READYWRITE,
                ]
            ),
        ),
    )


class SharedGalleryImageTransformer(Transformer):
    """
    convert an azure VHD to SIG
    """

    __sig_name = "url"

    @classmethod
    def type_name(cls) -> str:
        return "azure_sig"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return SigTransformerSchema

    @property
    def _output_names(self) -> List[str]:
        return [self.__sig_name]

    def _internal_run(self) -> Dict[str, Any]:
        runbook: SigTransformerSchema = self.runbook
        platform = _load_platform(self._runbook_builder, self.type_name())
        image_location = runbook.gallery_image_location[0]
        if not runbook.gallery_resource_group_location:
            runbook.gallery_resource_group_location = image_location
        if not runbook.gallery_location:
            runbook.gallery_location = image_location
        vhd_path = get_deployable_vhd_path(
            platform, runbook.vhd, image_location, self._log
        )
        vhd_details = get_vhd_details(platform, vhd_path)
        check_blob_exist(
            platform=platform,
            account_name=vhd_details["account_name"],
            container_name=vhd_details["container_name"],
            resource_group_name=vhd_details["resource_group_name"],
            blob_name=vhd_details["blob_name"],
            raise_error=True,
        )

        (
            gallery_image_publisher,
            gallery_image_offer,
            gallery_image_sku,
            gallery_image_version,
        ) = tuple(runbook.gallery_image_fullname.split())
        # create resource group if specified resource group doesn't exist
        check_or_create_resource_group(
            platform.credential,
            platform.subscription_id,
            platform.cloud,
            runbook.gallery_resource_group_name,
            runbook.gallery_location,
            self._log,
        )
        check_or_create_gallery(
            platform,
            runbook.gallery_resource_group_name,
            runbook.gallery_name,
            runbook.gallery_location,
            runbook.gallery_description,
        )

        check_or_create_gallery_image(
            platform,
            runbook.gallery_resource_group_name,
            runbook.gallery_name,
            runbook.gallery_image_name,
            image_location,
            gallery_image_publisher,
            gallery_image_offer,
            gallery_image_sku,
            runbook.gallery_image_ostype,
            runbook.gallery_image_osstate,
            runbook.gallery_image_hyperv_generation,
            runbook.gallery_image_architecture,
            runbook.gallery_image_securitytype,
        )

        check_or_create_gallery_image_version(
            platform,
            runbook.gallery_resource_group_name,
            runbook.gallery_name,
            runbook.gallery_image_name,
            gallery_image_version,
            image_location,
            runbook.regional_replica_count,
            runbook.storage_account_type,
            runbook.host_caching_type,
            vhd_path,
            vhd_details["resource_group_name"],
            vhd_details["account_name"],
            runbook.gallery_image_location,
        )

        sig_url = (
            f"{runbook.gallery_name}/"
            f"{runbook.gallery_image_name}/"
            f"{gallery_image_version}"
        )

        self._log.info(f"SIG Url: {sig_url}")
        return {self.__sig_name: sig_url}
