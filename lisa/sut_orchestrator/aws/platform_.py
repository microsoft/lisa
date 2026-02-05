# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional, Type, Union, cast

import boto3
from botocore.exceptions import ClientError
from dataclasses_json import dataclass_json
from marshmallow import fields, validate
from mypy_boto3_ec2.literals import InstanceTypeType
from mypy_boto3_ec2.type_defs import InstanceTypeInfoTypeDef, IpPermissionTypeDef
from retry import retry

from lisa import feature, schema, search_space
from lisa.environment import Environment
from lisa.node import Node, RemoteNode
from lisa.platform_ import Platform
from lisa.secret import add_secret
from lisa.util import (
    LisaException,
    constants,
    field_metadata,
    get_public_key_data,
    strip_strs,
)
from lisa.util.logger import Logger

from .. import AWS
from . import features
from .common import (
    AwsNodeSchema,
    AwsVmMarketplaceSchema,
    DataDiskCreateOption,
    DataDiskSchema,
    get_environment_context,
    get_node_context,
)

VM_SIZE_FALLBACK_PATTERNS = [
    re.compile(r"t[\d]_[\D]]"),
    re.compile(r".*"),
]
LOCATIONS = [
    "us-east-1",
    "us-east-2",
    "us-west-1",
    "us-west-2",
    "af-south-1",
    "ap-east-1",
    "ap-northeast-1",
    "eu-west-1",
    "eu-central-1",
    "sa-east-1",
]
DEFAULT_LOCATION = "us-west-2"


@dataclass_json()
@dataclass
class AwsDeployParameter:
    location: str = ""
    key_pair_name: str = ""
    security_group_name: str = ""
    security_group_id: str = ""
    subnet_count: int = 1
    nodes: List[AwsNodeSchema] = field(default_factory=list)
    data_disks: List[DataDiskSchema] = field(default_factory=list)


@dataclass_json()
@dataclass
class AwsCapability:
    location: str
    vm_size: str
    capability: schema.NodeSpace
    estimated_cost: int
    resource_sku: InstanceTypeInfoTypeDef

    def __post_init__(self, *args: Any, **kwargs: Any) -> None:
        # reload features settings with platform specified types.
        _convert_to_aws_node_space(self.capability)


@dataclass_json()
@dataclass
class AwsLocation:
    updated_time: datetime = field(
        default_factory=datetime.now,
        metadata=field_metadata(
            fields.DateTime,
            encoder=datetime.isoformat,
            decoder=datetime.fromisoformat,
            format="iso",
        ),
    )
    location: str = ""
    capabilities: List[AwsCapability] = field(default_factory=list)


@dataclass_json()
@dataclass
class AwsPlatformSchema:
    aws_access_key_id: str = field(default="")
    aws_secret_access_key: str = field(default="")
    aws_session_token: str = field(default="")
    aws_default_region: str = field(default="")
    security_group_name: str = field(default="")
    key_pair_name: str = field(default="")
    locations: Optional[Union[str, List[str]]] = field(default=None)

    log_level: str = field(
        default=logging.getLevelName(logging.WARN),
        metadata=field_metadata(
            validate=validate.OneOf(
                [
                    logging.getLevelName(logging.ERROR),
                    logging.getLevelName(logging.WARN),
                    logging.getLevelName(logging.INFO),
                    logging.getLevelName(logging.DEBUG),
                ]
            ),
        ),
    )

    # do actual deployment, or pass through for troubleshooting
    dry_run: bool = False
    # do actual deployment, or try to retrieve existing vms
    deploy: bool = True
    # wait resource deleted or not
    wait_delete: bool = False

    def __post_init__(self, *args: Any, **kwargs: Any) -> None:
        strip_strs(
            self,
            [
                "aws_access_key_id",
                "aws_secret_access_key",
                "aws_session_token",
                "aws_default_region",
                "security_group_name",
                "key_pair_name",
                "locations",
                "log_level",
            ],
        )

        if self.aws_access_key_id:
            add_secret(self.aws_access_key_id)
        if self.aws_secret_access_key:
            add_secret(self.aws_secret_access_key)
        if self.aws_session_token:
            add_secret(self.aws_session_token)

        if not self.locations:
            self.locations = LOCATIONS


class AwsPlatform(Platform):
    _locations_data_cache: Dict[str, AwsLocation] = {}
    _eligible_capabilities: Dict[str, List[AwsCapability]] = {}

    def __init__(self, runbook: schema.Platform) -> None:
        super().__init__(runbook=runbook)

    @classmethod
    def type_name(cls) -> str:
        return AWS

    @classmethod
    def supported_features(cls) -> List[Type[feature.Feature]]:
        return [
            features.Gpu,
            features.SerialConsole,
            features.StartStop,
            features.NetworkInterface,
            features.Disk,
        ]

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        # set needed environment variables for authentication
        aws_runbook: AwsPlatformSchema = self.runbook.get_extended_runbook(
            AwsPlatformSchema
        )
        assert aws_runbook, "platform runbook cannot be empty"

        self._aws_runbook = aws_runbook
        self._initialize_credential()
        # boto3 client is thread safe
        self._ec2_client = boto3.client("ec2")

    def _initialize_credential(self) -> None:
        aws_runbook = self._aws_runbook
        if aws_runbook.aws_access_key_id:
            os.environ["AWS_ACCESS_KEY_ID"] = aws_runbook.aws_access_key_id
        if aws_runbook.aws_secret_access_key:
            os.environ["AWS_SECRET_ACCESS_KEY"] = aws_runbook.aws_secret_access_key
        if aws_runbook.aws_session_token:
            os.environ["AWS_SESSION_TOKEN"] = aws_runbook.aws_session_token
        if aws_runbook.aws_default_region:
            os.environ["AWS_DEFAULT_REGION"] = aws_runbook.aws_default_region

    def _create_key_pair(self, key_name: str, private_key_file: str) -> Any:
        try:
            ec2_resource = boto3.resource("ec2")
            key_pair = ec2_resource.import_key_pair(
                KeyName=key_name,
                PublicKeyMaterial=get_public_key_data(private_key_file),
            )
            self._log.info("Created key %s.", key_pair.name)
        except ClientError:
            self._log.error("Couldn't create key %s.", key_name)
            raise
        else:
            return key_pair

    def _check_or_create_security_group(  # noqa: C901
        self, security_group_name: str, group_description: str
    ) -> Any:
        try:
            ec2_resource = boto3.resource("ec2")

            # By default, AWS users can create up to 5 VPCs
            for i in range(50, 55):
                cidr_block = "173." + str(i) + ".0.0/16"
                vpcs = list(
                    ec2_resource.vpcs.filter(
                        Filters=[{"Name": "cidr", "Values": [cidr_block]}]
                    )
                )
                if len(vpcs) == 0:
                    self._vpc = ec2_resource.create_vpc(CidrBlock=cidr_block)
                    self._log.info(
                        f"Create a new VPC: {self._vpc.id}"
                        f"with CIDR block {self._vpc.cidr_block}"
                    )
                    self._internet_gateway = ec2_resource.create_internet_gateway()
                    self._vpc.attach_internet_gateway(
                        InternetGatewayId=self._internet_gateway.id
                    )
                    self._route_table = ec2_resource.create_route_table(
                        VpcId=self._vpc.id
                    )
                    self._route_table.create_route(
                        DestinationCidrBlock="0.0.0.0/0",
                        GatewayId=self._internet_gateway.id,
                    )
                    self._log.info(
                        "Create an internet gateway: %s and a route table %s",
                        self._internet_gateway.id,
                        self._route_table.id,
                    )
                    break

            if self._vpc is None:
                raise LisaException(
                    "Couldn't get/create VPCs as there are 5 exiting VPCs."
                    "Please wait for others finishing test."
                )
        except ClientError:
            self._log.exception("Couldn't get/create VPCs.")
            raise

        try:
            security_group = self._vpc.create_security_group(
                GroupName=security_group_name, Description=group_description
            )
            self._log.info(
                "Created security group %s in VPC %s.",
                security_group_name,
                self._vpc.id,
            )
        except ClientError:
            self._log.exception(
                "Couldn't create security group %s.", security_group_name
            )
            raise

        try:
            ip_permissions: List[IpPermissionTypeDef] = [
                {
                    # SSH ingress open to anyone
                    "IpProtocol": "tcp",
                    "FromPort": 22,
                    "ToPort": 22,
                    "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
                },
                {
                    # Open to ips in the vpc
                    "IpProtocol": "-1",
                    "FromPort": -1,
                    "ToPort": -1,
                    "IpRanges": [{"CidrIp": self._vpc.cidr_block}],
                },
            ]

            security_group.authorize_ingress(IpPermissions=ip_permissions)
            self._log.info("Set inbound rules for %s to allow SSH.", security_group.id)
        except ClientError:
            self._log.exception(
                "couldn't authorize inbound rules for %s.", security_group_name
            )
            raise
        else:
            return security_group

    def _prepare_environment(  # noqa: C901
        self, environment: Environment, log: Logger
    ) -> bool:
        # TODO: Reduce this function's complexity and remove the disabled warning.
        """
        Main flow

        1. load location, vm size patterns firstly.
        2. load available vm sizes for each location.
        3. match vm sizes by pattern.

        for each environment
        1. If predefined location exists on node level, check conflict and use it.
        2. If predefined vm size exists on node level, check exists and use it.
        3. check capability for each node by order of pattern.
        4. get min capability for each match
        """
        is_success: bool = True
        ec2_resource = boto3.resource("ec2")

        if environment.runbook.nodes_requirement:
            is_success = False
            nodes_requirement = environment.runbook.nodes_requirement
            node_count = len(nodes_requirement)
            # fills predefined locations here.
            predefined_caps: List[Any] = [None] * node_count
            # make sure all vms are in same location.
            existing_location: str = ""
            predefined_cost: float = 0

            for req in nodes_requirement:
                # covert to aws node space, so the aws extensions can be loaded.
                _convert_to_aws_node_space(req)

                # check locations
                # apply aws specified values
                node_runbook: AwsNodeSchema = req.get_extended_runbook(
                    AwsNodeSchema, AWS
                )
                if node_runbook.location:
                    if existing_location:
                        # if any one has different location, calculate again
                        if existing_location != node_runbook.location:
                            raise LisaException(
                                f"predefined node must be in same location, "
                                f"previous: {existing_location}, "
                                f"found: {node_runbook.location}"
                            )
                    else:
                        existing_location = node_runbook.location

            if existing_location:
                locations = [existing_location]
            else:
                locations = LOCATIONS

            # check eligible locations
            found_or_skipped = False
            for location_name in locations:
                predefined_cost = 0
                predefined_caps = [None] * node_count
                for req_index, req in enumerate(nodes_requirement):
                    found_or_skipped = False
                    node_runbook = req.get_extended_runbook(AwsNodeSchema, AWS)
                    if not node_runbook.vm_size:
                        # not to check, if no vm_size set
                        found_or_skipped = True
                        continue

                    # find predefined vm size on all available's.
                    location_info: AwsLocation = self._get_location_info(
                        location_name, log
                    )
                    matched_score: float = 0
                    matched_cap: Optional[AwsCapability] = None
                    matcher = SequenceMatcher(None, node_runbook.vm_size.lower(), "")
                    for aws_cap in location_info.capabilities:
                        matcher.set_seq2(aws_cap.vm_size.lower())
                        if (
                            node_runbook.vm_size.lower() in aws_cap.vm_size.lower()
                            and matched_score < matcher.ratio()
                        ):
                            matched_cap = aws_cap
                            matched_score = matcher.ratio()
                    if matched_cap:
                        predefined_cost += matched_cap.estimated_cost

                        min_cap = self._generate_min_capability(
                            req, matched_cap, location_name
                        )

                        if not existing_location:
                            existing_location = location_name
                        predefined_caps[req_index] = min_cap
                        found_or_skipped = True
                    else:
                        # if not found any, skip and try next location
                        break
                if found_or_skipped:
                    # if found all, skip other locations
                    break

            if found_or_skipped:
                for location_name in locations:
                    # in each location, all node must be found
                    # fill them as None and check after met capability
                    found_capabilities: List[Any] = list(predefined_caps)

                    # skip unmatched location
                    if existing_location and existing_location != location_name:
                        continue

                    estimated_cost: float = 0
                    location_caps = self.get_eligible_vm_sizes(location_name, log)
                    for req_index, req in enumerate(nodes_requirement):
                        node_runbook = req.get_extended_runbook(AwsNodeSchema, AWS)
                        image = ec2_resource.Image(node_runbook.get_image_id())

                        for aws_cap in location_caps:
                            if found_capabilities[req_index]:
                                # found, so skipped
                                break
                            # Check if the instance type is on the same architecture
                            # as the image.
                            processor_info = aws_cap.resource_sku["ProcessorInfo"]
                            supported_archs = processor_info["SupportedArchitectures"]
                            if image.architecture != supported_archs[0]:
                                continue

                            check_result = req.check(aws_cap.capability)
                            if check_result.result:
                                min_cap = self._generate_min_capability(
                                    req, aws_cap, aws_cap.location
                                )

                                estimated_cost += aws_cap.estimated_cost

                                found_capabilities[req_index] = min_cap
                        if all(x for x in found_capabilities):
                            break

                    if all(x for x in found_capabilities):
                        # all found and replace current requirement
                        environment.runbook.nodes_requirement = found_capabilities
                        environment.cost = estimated_cost + predefined_cost
                        is_success = True
                        log.debug(
                            f"requirement meet, "
                            f"cost: {environment.cost}, "
                            f"cap: {environment.runbook.nodes_requirement}"
                        )
                        break

        return is_success

    def _deploy_environment(self, environment: Environment, log: Logger) -> None:
        assert self._ec2_client
        assert self._aws_runbook

        environment_context = get_environment_context(environment=environment)
        normalized_run_name = constants.NORMALIZE_PATTERN.sub("_", constants.RUN_NAME)
        if self._aws_runbook.security_group_name:
            security_group_name = self._aws_runbook.security_group_name
        else:
            security_group_name = f"{normalized_run_name}__sec_group"
        if self._aws_runbook.key_pair_name:
            key_pair_name = self._aws_runbook.key_pair_name
        else:
            key_pair_name = f"{normalized_run_name}_keypair"

        environment_context.security_group_name = security_group_name
        environment_context.key_pair_name = key_pair_name
        if self._aws_runbook.dry_run:
            log.info(f"dry_run: {self._aws_runbook.dry_run}")
        else:
            try:
                if self._aws_runbook.deploy:
                    log.info(
                        f"creating or updating security group: [{security_group_name}]"
                    )
                    self._security_group = self._check_or_create_security_group(
                        security_group_name=security_group_name,
                        group_description="Lisa security group for testing.",
                    )
                    environment_context.security_group_is_created = True
                    environment_context.security_group_id = self._security_group.id

                    if self.runbook.admin_private_key_file:
                        self._key_pair = self._create_key_pair(
                            key_pair_name, self.runbook.admin_private_key_file
                        )
                else:
                    log.info(
                        f"reusing security group: [{security_group_name}]"
                        f" and key pair: [{key_pair_name}]"
                    )

                deployment_parameters = self._create_deployment_parameters(
                    security_group_name, environment, log
                )

                instances = {}
                if self._aws_runbook.deploy:
                    instances = self._deploy(deployment_parameters, log)

                # Even skipped deploy, try best to initialize nodes
                self._initialize_nodes(environment, instances, log)
            except Exception as e:
                self._delete_environment(environment, log)
                raise e

    def _create_deployment_parameters(
        self, security_group_name: str, environment: Environment, log: Logger
    ) -> AwsDeployParameter:
        assert environment.runbook, "env data cannot be None"
        assert environment.runbook.nodes_requirement, "node requirement cannot be None"

        log.debug("creating deployment")
        # construct parameters
        aws_parameters = AwsDeployParameter()

        environment_context = get_environment_context(environment=environment)
        aws_parameters.key_pair_name = environment_context.key_pair_name
        aws_parameters.security_group_name = environment_context.security_group_name
        aws_parameters.security_group_id = environment_context.security_group_id

        nodes_parameters: List[AwsNodeSchema] = []
        for node_space in environment.runbook.nodes_requirement:
            assert isinstance(
                node_space, schema.NodeSpace
            ), f"actual: {type(node_space)}"

            aws_node_runbook = node_space.get_extended_runbook(
                AwsNodeSchema, type_name=AWS
            )

            # init node
            node = environment.create_node_from_requirement(
                node_space,
            )
            aws_node_runbook = self._create_node_runbook(
                len(nodes_parameters),
                node_space,
                log,
            )
            # save parsed runbook back, for example, the version of marketplace may be
            # parsed from latest to a specified version.
            node.capability.set_extended_runbook(aws_node_runbook)
            nodes_parameters.append(aws_node_runbook)

            # Set data disk array
            aws_parameters.data_disks = self._generate_data_disks(
                node, aws_node_runbook
            )

            if not aws_parameters.location:
                # take first one's location
                aws_parameters.location = aws_node_runbook.location

            # save vm's information into node
            node_context = get_node_context(node)
            # vm's name, use to find it from aws
            node_context.vm_name = aws_node_runbook.name
            # ssh related information will be filled back once vm is created
            node_context.username = self.runbook.admin_username
            node_context.private_key_file = self.runbook.admin_private_key_file

            log.info(f"vm setting: {aws_node_runbook}")

        aws_parameters.nodes = nodes_parameters

        # In Azure, each VM should have only one nic in one subnet. So calculate
        # the max nic count, and set to subnet count.
        aws_parameters.subnet_count = max(x.nic_count for x in aws_parameters.nodes)

        # composite deployment properties
        parameters = aws_parameters.to_dict()  # type:ignore
        parameters = {k: {"value": v} for k, v in parameters.items()}
        log.debug(f"parameters: {parameters}")

        return aws_parameters

    def _create_node_runbook(
        self,
        index: int,
        node_space: schema.NodeSpace,
        log: Logger,
    ) -> AwsNodeSchema:
        aws_node_runbook = node_space.get_extended_runbook(AwsNodeSchema, type_name=AWS)

        if not aws_node_runbook.name:
            aws_node_runbook.name = f"node-{index}"
        if not aws_node_runbook.vm_size:
            raise LisaException("vm_size is not detected before deploy")
        if not aws_node_runbook.location:
            raise LisaException("location is not detected before deploy")

        if not aws_node_runbook.marketplace:
            # set to default marketplace, if nothing specified
            aws_node_runbook.marketplace = AwsVmMarketplaceSchema()

        # Set disk type
        assert node_space.disk, "node space must have disk defined."
        assert isinstance(node_space.disk.data_disk_type, schema.DiskType)
        aws_node_runbook.disk_type = features.get_aws_disk_type(
            node_space.disk.data_disk_type
        )
        aws_node_runbook.data_disk_caching_type = node_space.disk.data_disk_caching_type
        assert isinstance(
            node_space.disk.data_disk_iops, int
        ), f"actual: {type(node_space.disk.data_disk_iops)}"
        aws_node_runbook.data_disk_iops = node_space.disk.data_disk_iops
        assert isinstance(
            node_space.disk.data_disk_size, int
        ), f"actual: {type(node_space.disk.data_disk_size)}"
        aws_node_runbook.data_disk_size = node_space.disk.data_disk_size

        assert node_space.network_interface
        assert isinstance(
            node_space.network_interface.nic_count, int
        ), f"actual: {node_space.network_interface.nic_count}"
        aws_node_runbook.nic_count = node_space.network_interface.nic_count
        assert isinstance(
            node_space.network_interface.data_path, schema.NetworkDataPath
        ), f"actual: {type(node_space.network_interface.data_path)}"
        if node_space.network_interface.data_path == schema.NetworkDataPath.Sriov:
            aws_node_runbook.enable_sriov = True

        return aws_node_runbook

    def _deploy(
        self, deployment_parameters: AwsDeployParameter, log: Logger
    ) -> Dict[str, Any]:
        ec2_resource = boto3.resource("ec2")
        instances = {}
        subnets = self._create_subnets(self._vpc.id, deployment_parameters, log)
        block_device_mappings = self._create_block_devices(deployment_parameters, log)

        for node in deployment_parameters.nodes:
            network_interfaces = self._create_network_interfaces(
                deployment_parameters, node, subnets, log
            )

            try:
                instance = ec2_resource.create_instances(
                    ImageId=node.get_image_id(),
                    InstanceType=cast(InstanceTypeType, node.vm_size),
                    NetworkInterfaces=network_interfaces,
                    BlockDeviceMappings=block_device_mappings,
                    KeyName=deployment_parameters.key_pair_name,
                    MinCount=1,
                    MaxCount=1,
                )[0]

                instance.wait_until_running()
                instance.load()
                log.info("Created instance %s.", instance.id)

                # Enable ENA support if the test case requires.
                # Don't support the Intel 82599 Virtual Function (VF) interface now.
                # Refer to the document about AWS Enhanced networking on Linux.
                if node.enable_sriov and (not instance.ena_support):
                    self._ec2_client.modify_instance_attribute(
                        InstanceId=instance.id,
                        EnaSupport={
                            "Value": True,
                        },
                    )

                instances[node.name] = instance.instance_id
            except ClientError:
                log.exception(
                    "Couldn't create instance with image %s, "
                    "instance type %s, and key %s.",
                    node.get_image_id(),
                    node.vm_size,
                    deployment_parameters.key_pair_name,
                )
                raise

        return instances

    def _delete_environment(self, environment: Environment, log: Logger) -> None:
        environment_context = get_environment_context(environment=environment)
        security_group_name = environment_context.security_group_name
        # the resource group name is empty when it is not deployed for some reasons,
        # like capability doesn't meet case requirement.
        if not security_group_name:
            return
        assert self._aws_runbook

        if not environment_context.security_group_is_created:
            log.info(
                f"skipped to delete security resource group: {security_group_name}, "
                f"as it's not created by this run."
            )
        elif self._aws_runbook.dry_run:
            log.info(
                f"skipped to delete security resource group: {security_group_name}, "
                f"as it's a dry run."
            )
        else:
            ec2_resource = boto3.resource("ec2")
            for node in environment.nodes.list():
                node_context = get_node_context(node)
                instance_id = node_context.instance_id
                self.terminate_instance(ec2_resource, instance_id, log)

            self.delete_security_group(
                ec2_resource,
                environment_context.security_group_id,
                environment_context.security_group_name,
                log,
            )

            self.delete_key_pair(ec2_resource, environment_context.key_pair_name, log)

            try:
                log.info(f"deleting vpc: {self._vpc.id}")
                for association in self._route_table.associations:
                    association.delete()
                self._route_table.delete()
                self._internet_gateway.detach_from_vpc(VpcId=self._vpc.id)
                self._internet_gateway.delete()
                for subnet in self._vpc.subnets.all():
                    subnet.delete()
                self._vpc.delete()
            except ClientError:
                log.exception(
                    "Couldn't delete vpc %s.",
                    self._vpc.id,
                )
                raise

    def terminate_instance(
        self, ec2_resource: Any, instance_id: str, log: Logger
    ) -> None:
        if not instance_id:
            return

        try:
            instance = ec2_resource.Instance(instance_id)
            instance.terminate()
            instance.wait_until_terminated()
            log.info("Terminating instance %s.", instance_id)
        except ClientError:
            log.exception("Couldn't terminate instance %s.", instance_id)

    def delete_security_group(
        self, ec2_resource: Any, group_id: str, security_group_name: str, log: Logger
    ) -> None:
        try:
            ec2_resource.SecurityGroup(group_id).delete()
            log.info("Deleting security group: %s.", security_group_name)
        except ClientError:
            log.exception(
                "Couldn't delete security group %s.",
                security_group_name,
            )

    def delete_key_pair(self, ec2_resource: Any, key_name: str, log: Logger) -> None:
        try:
            ec2_resource.KeyPair(key_name).delete()
            log.info("Deleted key pair %s.", key_name)
        except ClientError:
            log.exception("Couldn't delete key pair %s.", key_name)

    def _create_subnets(
        self, vpc_id: str, deployment_parameters: AwsDeployParameter, log: Logger
    ) -> Dict[int, Any]:
        subnets: Dict[int, Any] = {}
        try:
            addrs = self._vpc.cidr_block.split(".")
            for i in range(deployment_parameters.subnet_count):
                cidr_block = f"{addrs[0]}.{addrs[1]}.{str(i)}.0/24"
                subnets[i] = self._ec2_client.create_subnet(
                    CidrBlock=cidr_block,
                    VpcId=vpc_id,
                )
                self._route_table.associate_with_subnet(
                    SubnetId=subnets[i]["Subnet"]["SubnetId"]
                )
        except ClientError:
            log.exception("Could not create a custom subnet.")
            raise
        else:
            return subnets

    def _create_network_interfaces(
        self,
        deployment_parameters: AwsDeployParameter,
        node: AwsNodeSchema,
        subnets: Dict[int, Any],
        log: Logger,
    ) -> List[Any]:
        network_interfaces = [
            {
                "Description": f"{node.name}-extra-0",
                "AssociatePublicIpAddress": True,
                "SubnetId": subnets[0]["Subnet"]["SubnetId"],
                "DeviceIndex": 0,
                "Groups": [deployment_parameters.security_group_id],
            }
        ]

        for i in range(1, node.nic_count):
            network_interfaces.append(
                {
                    "Description": f"{node.name}-extra-{i}",
                    "AssociatePublicIpAddress": False,
                    "SubnetId": subnets[i]["Subnet"]["SubnetId"],
                    "DeviceIndex": i,
                    "Groups": [deployment_parameters.security_group_id],
                }
            )

        return network_interfaces

    def _create_block_devices(
        self,
        deployment_parameters: AwsDeployParameter,
        log: Logger,
    ) -> List[Any]:
        # There are some instance volume limits, please refer to
        # https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/volume_limits.html#linux-specific-volume-limits
        block_device_mappings = []
        volumes = self._get_available_volumes(deployment_parameters)

        for idx, disk in enumerate(deployment_parameters.data_disks):
            if (
                disk.create_option
                == DataDiskCreateOption.DATADISK_CREATE_OPTION_TYPE_EMPTY
            ):
                if idx >= len(volumes):
                    raise LisaException(
                        f"No device names available "
                        f"for {len(deployment_parameters.data_disks)} disks!",
                    )

                block_device_mappings.append(
                    {
                        "DeviceName": volumes[idx],
                        "Ebs": {
                            "DeleteOnTermination": True,
                            "VolumeSize": disk.size,
                            "VolumeType": disk.type,
                            "Iops": disk.iops,
                        },
                    }
                )

        return block_device_mappings

    def _get_available_volumes(
        self, deployment_parameters: AwsDeployParameter
    ) -> List[str]:
        # In current implementation, all nodes use the same image.
        image_id = deployment_parameters.nodes[0].get_image_id()
        virtualization_type = boto3.resource("ec2").Image(image_id).virtualization_type
        volumes: List[str] = []

        # Create the available volume names based on virtualization type.
        # Refer to the following link
        # https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/device_naming.html
        if virtualization_type == "hvm":
            for c in range(ord("b"), ord("c") + 1):
                for p in range(ord("a"), ord("z") + 1):
                    volumes.append(f"/dev/xvd{chr(c)}{chr(p)}")
        elif virtualization_type == "paravirtual":
            for c in range(ord("f"), ord("p") + 1):
                for p in range(1, 7):
                    volumes.append(f"/dev/sd{chr(c)}{p}")
        else:
            raise LisaException(
                f"The virtualization type {virtualization_type} is not supported now."
            )

        return volumes

    def _initialize_nodes(
        self, environment: Environment, instances: Dict[str, Any], log: Logger
    ) -> None:
        ec2_resource = boto3.resource("ec2")
        node_context_map: Dict[str, Node] = {}
        for node in environment.nodes.list():
            node_context = get_node_context(node)
            node_context.instance_id = instances[node_context.vm_name]
            node_context_map[node_context.vm_name] = node

        for vm_name, node in node_context_map.items():
            node_context = get_node_context(node)
            vm = ec2_resource.Instance(node_context.instance_id)
            if not vm:
                raise LisaException(
                    f"cannot find vm: '{vm_name}', make sure deployment is correct."
                )

            public_ip = vm.public_ip_address
            assert public_ip, "public IP address cannot be empty!"

            if not node.name:
                node.name = vm_name

            assert isinstance(node, RemoteNode)
            node.set_connection_info(
                address=vm.private_ip_address,
                port=22,
                public_address=public_ip,
                public_port=22,
                username=node_context.username,
                password=node_context.password,
                private_key_file=node_context.private_key_file,
            )

    @retry(tries=10, delay=1, jitter=(0.5, 1))  # type: ignore
    def _load_location_info_from_file(
        self, cached_file_name: Path, log: Logger
    ) -> Optional[AwsLocation]:
        loaded_obj: Optional[AwsLocation] = None
        if cached_file_name.exists():
            try:
                with open(cached_file_name, "r") as f:
                    loaded_data: Dict[str, Any] = json.load(f)
                loaded_obj = schema.load_by_type(AwsLocation, loaded_data)
            except Exception as e:
                # if schema changed, There may be exception, remove cache and retry
                # Note: retry on this method depends on decorator
                log.debug(f"error on loading cache, delete cache and retry. {e}")
                cached_file_name.unlink()
                raise e
        return loaded_obj

    def _get_location_info(self, location: str, log: Logger) -> AwsLocation:
        cached_file_name = constants.CACHE_PATH.joinpath(
            f"aws_locations_{location}.json"
        )
        should_refresh: bool = True
        key = location
        location_data = self._locations_data_cache.get(key, None)
        if not location_data:
            location_data = self._load_location_info_from_file(
                cached_file_name=cached_file_name, log=log
            )

        if location_data:
            delta = datetime.now() - location_data.updated_time
            # refresh cached locations every 1 day.
            if delta.days < 1:
                should_refresh = False
                log.debug(
                    f"{key}: cache used: {location_data.updated_time}, "
                    f"sku count: {len(location_data.capabilities)}"
                )
            else:
                log.debug(
                    f"{key}: cache timeout: {location_data.updated_time},"
                    f"sku count: {len(location_data.capabilities)}"
                )
        else:
            log.debug(f"{key}: no cache found")
        if should_refresh:
            ec2_region = boto3.client("ec2", region_name=location)

            log.debug(f"{key}: querying")
            all_skus: List[AwsCapability] = []
            instance_types = ec2_region.describe_instance_types()
            for instance_type in instance_types["InstanceTypes"]:
                capability = self._instance_type_to_capability(location, instance_type)

                # estimate vm cost for priority
                assert isinstance(capability.core_count, int)
                assert isinstance(capability.gpu_count, int)
                estimated_cost = capability.core_count + capability.gpu_count * 100
                aws_capability = AwsCapability(
                    location=location,
                    vm_size=instance_type["InstanceType"],
                    capability=capability,
                    resource_sku=instance_type,
                    estimated_cost=estimated_cost,
                )
                all_skus.append(aws_capability)

            location_data = AwsLocation(location=location, capabilities=all_skus)
            log.debug(f"{location}: saving to disk")
            with open(cached_file_name, "w") as f:
                json.dump(location_data.to_dict(), f)  # type: ignore
            log.debug(f"{key}: new data, " f"sku: {len(location_data.capabilities)}")

        assert location_data
        self._locations_data_cache[key] = location_data
        return location_data

    def _instance_type_to_capability(  # noqa: C901
        self, location: str, instance_type: Any
    ) -> schema.NodeSpace:
        # fill in default values, in case no capability meet.
        node_space = schema.NodeSpace(
            node_count=1,
            core_count=0,
            memory_mb=0,
            gpu_count=0,
        )
        instancetype_name: str = instance_type["InstanceType"]
        node_space.name = f"{location}_{instancetype_name}"
        node_space.features = search_space.SetSpace[schema.FeatureSettings](
            is_allow_set=True
        )
        node_space.disk = features.AwsDiskOptionSettings()
        node_space.disk.data_disk_type = search_space.SetSpace[schema.DiskType](
            is_allow_set=True, items=[]
        )
        node_space.disk.data_disk_iops = search_space.IntRange(min=0)
        node_space.disk.data_disk_size = search_space.IntRange(min=0)
        node_space.network_interface = schema.NetworkInterfaceOptionSettings()
        node_space.network_interface.data_path = search_space.SetSpace[
            schema.NetworkDataPath
        ](is_allow_set=True, items=[])
        for name, value in instance_type.items():
            if name == "VCpuInfo":
                node_space.core_count = int(value["DefaultVCpus"])
            elif name == "MemoryInfo":
                node_space.memory_mb = int(value["SizeInMiB"])
            elif name == "NetworkInfo":
                nic_count = value["MaximumNetworkInterfaces"]
                node_space.network_interface.nic_count = search_space.IntRange(
                    min=1, max=nic_count
                )
                node_space.network_interface.max_nic_count = nic_count
                if value["EnaSupport"] == "supported":
                    node_space.network_interface.data_path.add(
                        schema.NetworkDataPath.Sriov
                    )
            elif name == "GpuInfo":
                for gpu in value["Gpus"]:
                    node_space.gpu_count += gpu["Count"]
                # update features list if gpu feature is supported
                node_space.features.add(
                    schema.FeatureSettings.create(features.Gpu.name())
                )

        # all nodes support following features
        node_space.features.update(
            [
                schema.FeatureSettings.create(features.StartStop.name()),
                schema.FeatureSettings.create(features.SerialConsole.name()),
            ]
        )
        node_space.disk.data_disk_type.add(schema.DiskType.StandardHDDLRS)
        node_space.disk.data_disk_type.add(schema.DiskType.StandardSSDLRS)
        node_space.disk.data_disk_type.add(schema.DiskType.PremiumSSDLRS)
        node_space.network_interface.data_path.add(schema.NetworkDataPath.Synthetic)

        return node_space

    def get_eligible_vm_sizes(self, location: str, log: Logger) -> List[AwsCapability]:
        # load eligible vm sizes
        # 1. vm size supported in current location
        # 2. vm size match predefined pattern

        location_capabilities: List[AwsCapability] = []

        key = self._get_location_key(location)
        if key not in self._eligible_capabilities:
            location_info: AwsLocation = self._get_location_info(location, log)
            # loop all fall back levels
            for fallback_pattern in VM_SIZE_FALLBACK_PATTERNS:
                level_capabilities: List[AwsCapability] = []

                # loop all capabilities
                for aws_capability in location_info.capabilities:
                    # exclude one core which may be too slow to work in some distro
                    assert isinstance(aws_capability.capability.core_count, int)
                    if (
                        fallback_pattern.match(aws_capability.vm_size)
                        and aws_capability.capability.core_count > 1
                    ):
                        level_capabilities.append(aws_capability)

                # sort by rough cost
                level_capabilities.sort(key=lambda x: (x.estimated_cost))
                log.debug(
                    f"{key}, pattern '{fallback_pattern.pattern}'"
                    f" {len(level_capabilities)} candidates: "
                    f"{[x.vm_size for x in level_capabilities]}"
                )
                location_capabilities.extend(level_capabilities)
            self._eligible_capabilities[key] = location_capabilities
        return self._eligible_capabilities[key]

    def _get_location_key(self, location: str) -> str:
        return f"lisa_aws_{location}"

    def _generate_min_capability(
        self,
        requirement: schema.NodeSpace,
        aws_capability: AwsCapability,
        location: str,
    ) -> schema.NodeSpace:
        min_cap: schema.NodeSpace = requirement.generate_min_capability(
            aws_capability.capability
        )
        # Apply aws specified values.
        aws_node_runbook = min_cap.get_extended_runbook(AwsNodeSchema, AWS)
        if aws_node_runbook.location:
            assert aws_node_runbook.location == location, (
                f"predefined location [{aws_node_runbook.location}] "
                f"must be same as "
                f"cap location [{location}]"
            )
        # the location may not be set
        aws_node_runbook.location = location
        aws_node_runbook.vm_size = aws_capability.vm_size
        assert min_cap.network_interface
        assert isinstance(
            min_cap.network_interface.nic_count, int
        ), f"actual: {min_cap.network_interface.nic_count}"
        aws_node_runbook.nic_count = min_cap.network_interface.nic_count
        assert isinstance(
            min_cap.network_interface.data_path, schema.NetworkDataPath
        ), f"actual: {type(min_cap.network_interface.data_path)}"
        if min_cap.network_interface.data_path == schema.NetworkDataPath.Sriov:
            aws_node_runbook.enable_sriov = True

        assert min_cap.disk, "disk must exists"
        assert isinstance(
            min_cap.disk.data_disk_count, int
        ), f"actual: {min_cap.disk.data_disk_count}"
        aws_node_runbook.data_disk_count = min_cap.disk.data_disk_count
        assert isinstance(
            min_cap.disk.data_disk_caching_type, str
        ), f"actual: {min_cap.disk.data_disk_caching_type}"
        aws_node_runbook.data_disk_caching_type = min_cap.disk.data_disk_caching_type

        return min_cap

    def _generate_data_disks(
        self,
        node: Node,
        aws_node_runbook: AwsNodeSchema,
    ) -> List[DataDiskSchema]:
        data_disks: List[DataDiskSchema] = []
        assert node.capability.disk
        if aws_node_runbook.marketplace:
            image = boto3.resource("ec2").Image(aws_node_runbook.marketplace.imageid)

            # AWS images has the root data disks by default
            for data_disk in image.block_device_mappings:
                if "Ebs" in data_disk and "VolumeSize" in data_disk["Ebs"]:
                    assert isinstance(node.capability.disk.data_disk_iops, int)
                    data_disks.append(
                        DataDiskSchema(
                            node.capability.disk.data_disk_caching_type,
                            data_disk["Ebs"]["VolumeSize"],
                            node.capability.disk.data_disk_iops,
                            aws_node_runbook.disk_type,
                            DataDiskCreateOption.DATADISK_CREATE_OPTION_TYPE_FROM_IMAGE,
                        )
                    )
        assert isinstance(
            node.capability.disk.data_disk_count, int
        ), f"actual: {type(node.capability.disk.data_disk_count)}"
        for _ in range(node.capability.disk.data_disk_count):
            assert isinstance(node.capability.disk.data_disk_size, int)
            assert isinstance(node.capability.disk.data_disk_iops, int)
            data_disks.append(
                DataDiskSchema(
                    node.capability.disk.data_disk_caching_type,
                    node.capability.disk.data_disk_size,
                    node.capability.disk.data_disk_iops,
                    aws_node_runbook.disk_type,
                    DataDiskCreateOption.DATADISK_CREATE_OPTION_TYPE_EMPTY,
                )
            )
        return data_disks


def _convert_to_aws_node_space(node_space: schema.NodeSpace) -> None:
    if node_space:
        if node_space.features:
            new_settings = search_space.SetSpace[schema.FeatureSettings](
                is_allow_set=True
            )
            for current_settings in node_space.features:
                # reload to type specified settings
                settings_type = feature.get_feature_settings_type_by_name(
                    current_settings.type, AwsPlatform.supported_features()
                )
                new_settings.add(schema.load_by_type(settings_type, current_settings))
            node_space.features = new_settings
        if node_space.disk:
            node_space.disk = schema.load_by_type(
                features.AwsDiskOptionSettings, node_space.disk
            )
        if node_space.network_interface:
            node_space.network_interface = schema.load_by_type(
                schema.NetworkInterfaceOptionSettings, node_space.network_interface
            )
