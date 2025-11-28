# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import base64
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Type

import boto3
from assertpy import assert_that
from dataclasses_json import dataclass_json

from lisa import features, schema, search_space
from lisa.features.gpu import ComputeSDK
from lisa.node import Node
from lisa.operating_system import CentOs, Redhat, Suse, Ubuntu
from lisa.search_space import RequirementMethod
from lisa.util import LisaException, set_filtered_fields

if TYPE_CHECKING:
    from .platform_ import AwsPlatform

from .. import AWS
from .common import AwsNodeSchema, get_node_context


class AwsFeatureMixin:
    def _initialize_information(self, node: Node) -> None:
        node_context = get_node_context(node)
        self._instance_id = node_context.instance_id


class StartStop(AwsFeatureMixin, features.StartStop):
    def _stop(
        self,
        wait: bool = True,
        state: features.StopState = features.StopState.Shutdown,
    ) -> None:
        ec2_resource = boto3.resource("ec2")
        instance = ec2_resource.Instance(self._instance_id)

        if state == features.StopState.Hibernate:
            instance.stop(Hibernate=True)
        else:
            instance.stop()
        if wait:
            instance.wait_until_stopped()

    def _start(self, wait: bool = True) -> None:
        ec2_resource = boto3.resource("ec2")
        instance = ec2_resource.Instance(self._instance_id)

        instance.start()
        if wait:
            instance.wait_until_running()

    def _restart(self, wait: bool = True) -> None:
        ec2_resource = boto3.resource("ec2")
        instance = ec2_resource.Instance(self._instance_id)

        instance.reboot()
        if wait:
            instance.wait_until_running()

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        super()._initialize(*args, **kwargs)
        self._initialize_information(self._node)


def get_aws_disk_type(disk_type: schema.DiskType) -> str:
    assert isinstance(disk_type, schema.DiskType), (
        f"the disk_type must be one value when calling get_disk_type. "
        f"But it's {disk_type}"
    )

    result = _disk_type_mapping.get(disk_type, None)
    assert result, f"unknown disk type: {disk_type}"

    return result


# There are more disk types in AWS than Azure, like io2/gp3/io 2 Block Express.
# If need to verify the storage performance of other types, please update the mapping.
# Refer to https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ebs-volume-types.html.
# DiskType.Ephemeral is not supported on AWS now.
_disk_type_mapping: Dict[schema.DiskType, str] = {
    schema.DiskType.PremiumSSDLRS: "io1",
    schema.DiskType.StandardHDDLRS: "st1",
    schema.DiskType.StandardSSDLRS: "gp3",
}


# Tuple: (IOPS, Disk Size)
_disk_size_iops_map: Dict[schema.DiskType, List[Tuple[int, int]]] = {
    schema.DiskType.PremiumSSDLRS: [
        (100, 4),
        (1000, 64),
        (5000, 128),
        (10000, 256),
        (20000, 1024),
        (32000, 2048),
        (50000, 8192),
        (64000, 16384),
    ],
    schema.DiskType.StandardHDDLRS: [
        (100, 125),
        (200, 8192),
        (500, 16384),
    ],
    schema.DiskType.StandardSSDLRS: [
        (3000, 1),
        (6000, 128),
        (8000, 256),
        (10000, 512),
        (12000, 1024),
        (14000, 4096),
        (16000, 16384),
    ],
}


class SerialConsole(AwsFeatureMixin, features.SerialConsole):
    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        super()._initialize(*args, **kwargs)
        self._initialize_information(self._node)

    def _get_console_log(self, saved_path: Optional[Path]) -> bytes:
        platform: AwsPlatform = self._platform  # type: ignore
        ec2_client = platform._ec2_client

        if saved_path:
            screenshot_response = ec2_client.get_console_screenshot(
                InstanceId=self._instance_id
            )
            screenshot_name = saved_path.joinpath("serial_console.jpg")
            with open(screenshot_name, "wb") as f:
                f.write(
                    base64.decodebytes(screenshot_response["ImageData"].encode("utf-8"))
                )

        diagnostic_data = ec2_client.get_console_output(InstanceId=self._instance_id)
        output_bytes = diagnostic_data["Output"].encode("ascii")
        return base64.b64decode(output_bytes)


class NetworkInterface(AwsFeatureMixin, features.NetworkInterface):
    """
    This Network interface feature is mainly to associate Aws
    network interface options settings.
    """

    @classmethod
    def settings_type(cls) -> Type[schema.FeatureSettings]:
        return schema.NetworkInterfaceOptionSettings

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        super()._initialize(*args, **kwargs)
        self._initialize_information(self._node)

    def _get_primary(self, nics: List[Any]) -> Any:
        for nic in nics:
            if nic["Attachment"]["DeviceIndex"] == 0:
                return nic

        raise LisaException(f"failed to find primary nic for vm {self._node.name}")

    def switch_sriov(
        self, enable: bool, wait: bool = True, reset_connections: bool = True
    ) -> None:
        aws_platform: AwsPlatform = self._platform  # type: ignore
        instance = boto3.resource("ec2").Instance(self._instance_id)

        # Don't check Intel 82599 Virtual Function (VF) interface at current
        if instance.ena_support == enable:
            self._log.debug(
                f"The accelerated networking default "
                f"status [{instance.ena_support}] is "
                f"consistent with set status [{enable}], no need to update."
            )
        else:
            self._log.debug(
                f"The accelerated networking default "
                f"status [{instance.ena_support}], "
                f"now set its status into [{enable}]."
            )
            aws_platform._ec2_client.modify_instance_attribute(
                InstanceId=instance.id,
                EnaSupport={
                    "Value": enable,
                },
            )

            instance.reload()
            assert_that(instance.ena_support).described_as(
                f"fail to set network interface accelerated "
                f"networking into status [{enable}]"
            ).is_equal_to(enable)

    def is_enabled_sriov(self) -> bool:
        instance = boto3.resource("ec2").Instance(self._instance_id)
        return instance.ena_support  # type: ignore

    def attach_nics(
        self, extra_nic_count: int, enable_accelerated_networking: bool = True
    ) -> None:
        aws_platform: AwsPlatform = self._platform  # type: ignore
        ec2_resource = boto3.resource("ec2")
        instance = ec2_resource.Instance(self._instance_id)

        current_nic_count = len(instance.network_interfaces)
        nic_count_after_add_extra = extra_nic_count + current_nic_count
        assert (
            self._node.capability.network_interface
            and self._node.capability.network_interface.max_nic_count
        )
        assert isinstance(
            self._node.capability.network_interface.max_nic_count, int
        ), f"actual: {type(self._node.capability.network_interface.max_nic_count)}"
        node_capability_nic_count = (
            self._node.capability.network_interface.max_nic_count
        )
        if nic_count_after_add_extra > node_capability_nic_count:
            raise LisaException(
                f"nic count after add extra nics is {nic_count_after_add_extra},"
                f" it exceeds the vm size's capability {node_capability_nic_count}."
            )
        nic = self._get_primary(instance.network_interfaces_attribute)

        index = current_nic_count
        while index < current_nic_count + extra_nic_count - 1:
            extra_nic_name = f"{self._node.name}-extra-{index}"
            self._log.debug(f"start to create the nic {extra_nic_name}.")
            network_interface = ec2_resource.create_network_interface(
                Description=extra_nic_name,
                Groups=[
                    nic["Groups"][0]["GroupId"],
                ],
                SubnetId=nic["SubnetId"],
            )

            self._log.debug(
                f"start to attach the nic {extra_nic_name} into VM {self._node.name}."
            )
            aws_platform._ec2_client.attach_network_interface(
                DeviceIndex=index,
                InstanceId=instance.id,
                NetworkInterfaceId=network_interface.network_interface_id,
            )
            self._log.debug(
                f"attach the nic {extra_nic_name} into"
                f"VM {self._node.name} successfully."
            )

            index += 1

    def remove_extra_nics(self) -> None:
        aws_platform: AwsPlatform = self._platform  # type: ignore
        instance = boto3.resource("ec2").Instance(self._instance_id)

        for network_interface in instance.network_interfaces_attribute:
            if network_interface["Attachment"]["DeviceIndex"] != 0:
                aws_platform._ec2_client.detach_network_interface(
                    AttachmentId=network_interface["Attachment"]["AttachmentId"]
                )
                aws_platform._ec2_client.delete_network_interface(
                    NetworkInterfaceId=network_interface["NetworkInterfaceId"]
                )

        nic = self._get_primary(instance.network_interfaces_attribute)
        networkinterface_id: str = nic["NetworkInterfaceId"]
        self._log.debug(
            f"Only associated nic {networkinterface_id} into VM {self._node.name}."
        )


# TODO: GPU feature is not verified yet.
class Gpu(AwsFeatureMixin, features.Gpu):
    # Only contains some types of ec2 instances which support GPU here.
    # Please refer to the following link for more types:
    # https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/install-nvidia-driver.html
    grid_supported_skus = [
        "g3s.xlarge",
        "g3.4xlarge",
        "g4dn.xlarge",
        "g5.xlarge",
        "g5.2xlarge",
    ]
    cuda_supported_skus = [
        "g3s.xlarge",
        "g3.4xlarge",
        "g4dn.xlarge",
        "g5.xlarge",
        "g5.2xlarge",
        "p2.xlarge",
        "p3.2xlarge",
    ]

    def is_supported(self) -> bool:
        # TODO: more supportability can be defined here
        supported_distro = (CentOs, Redhat, Ubuntu, Suse)
        if isinstance(self._node.os, supported_distro):
            return True

        return False

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        super()._initialize(*args, **kwargs)
        self._initialize_information(self._node)

    def _get_supported_driver(self) -> List[ComputeSDK]:
        driver_list = []
        node_runbook = self._node.capability.get_extended_runbook(AwsNodeSchema, AWS)
        if any(map((node_runbook.vm_size).__contains__, self.grid_supported_skus)):
            driver_list.append(ComputeSDK.GRID)
        if any(map((node_runbook.vm_size).__contains__, self.cuda_supported_skus)):
            driver_list.append(ComputeSDK.CUDA)

        if not driver_list:
            raise LisaException(
                "No valid Compute SDK found to install for the VM size -"
                f" {node_runbook.vm_size}."
            )
        return driver_list


class Disk(AwsFeatureMixin, features.Disk):
    """
    This Disk feature is mainly to associate Aws disk options settings.
    """

    @classmethod
    def settings_type(cls) -> Type[schema.FeatureSettings]:
        return AwsDiskOptionSettings

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        super()._initialize(*args, **kwargs)
        self._initialize_information(self._node)

    def get_raw_data_disks(self) -> List[str]:
        # Return all EBS devices except the root device
        instance = boto3.resource("ec2").Instance(self._instance_id)
        disk_array: List[str] = []

        for device_mapping in instance.block_device_mappings:
            if "Ebs" in device_mapping and "DeviceName" in device_mapping:
                if device_mapping["DeviceName"] != instance.root_device_name:
                    disk_array.append(device_mapping["DeviceName"])

        return disk_array


@dataclass_json()
@dataclass()
class AwsDiskOptionSettings(schema.DiskOptionSettings):
    def __eq__(self, o: object) -> bool:
        if not super().__eq__(o):
            return False

        assert isinstance(o, AwsDiskOptionSettings), f"actual: {type(o)}"
        return super().__eq__(o)

    # It uses to override requirement operations.
    def check(self, capability: Any) -> search_space.ResultReason:
        assert isinstance(
            capability, AwsDiskOptionSettings
        ), f"actual: {type(capability)}"
        result = super().check(capability)

        result.merge(
            search_space.check_setspace(self.data_disk_type, capability.data_disk_type),
            "disk_type",
        )
        result.merge(
            search_space.check_countspace(
                self.data_disk_count, capability.data_disk_count
            ),
            "data_disk_count",
        )
        result.merge(
            search_space.check_countspace(
                self.data_disk_iops, capability.data_disk_iops
            ),
            "data_disk_iops",
        )
        result.merge(
            search_space.check_countspace(
                self.data_disk_size, capability.data_disk_size
            ),
            "data_disk_size",
        )
        result.merge(
            search_space.check_countspace(
                self.max_data_disk_count, capability.max_data_disk_count
            ),
            "max_data_disk_count",
        )

        return result

    def _call_requirement_method(
        self, method: RequirementMethod, capability: Any
    ) -> Any:
        assert isinstance(
            capability, AwsDiskOptionSettings
        ), f"actual: {type(capability)}"

        assert (
            capability.data_disk_type
        ), "capability should have at least one disk type, but it's None"
        value = AwsDiskOptionSettings()
        super_value = schema.DiskOptionSettings._call_requirement_method(
            self, method, capability
        )
        set_filtered_fields(super_value, value, ["data_disk_count"])

        cap_disk_type = capability.data_disk_type
        if isinstance(cap_disk_type, search_space.SetSpace):
            assert (
                len(cap_disk_type) > 0
            ), "capability should have at least one disk type, but it's empty"
        elif isinstance(cap_disk_type, schema.DiskType):
            cap_disk_type = search_space.SetSpace[schema.DiskType](
                is_allow_set=True, items=[cap_disk_type]
            )
        else:
            raise LisaException(
                f"unknown disk type on capability, type: {cap_disk_type}"
            )

        value.data_disk_type = getattr(
            search_space, f"{method.value}_setspace_by_priority"
        )(self.data_disk_type, capability.data_disk_type, schema.disk_type_priority)

        # below values affect data disk only.
        if self.data_disk_count is not None or capability.data_disk_count is not None:
            value.data_disk_count = getattr(search_space, f"{method.value}_countspace")(
                self.data_disk_count, capability.data_disk_count
            )

        if (
            self.max_data_disk_count is not None
            or capability.max_data_disk_count is not None
        ):
            value.max_data_disk_count = getattr(
                search_space, f"{method.value}_countspace"
            )(self.max_data_disk_count, capability.max_data_disk_count)

        # The Ephemeral doesn't support data disk, but it needs a value. And it
        # doesn't need to calculate on intersect
        value.data_disk_iops = 0
        value.data_disk_size = 0

        if method == RequirementMethod.generate_min_capability:
            assert isinstance(
                value.data_disk_type, schema.DiskType
            ), f"actual: {type(value.data_disk_type)}"
            disk_type_iops = _disk_size_iops_map.get(value.data_disk_type, None)
            # ignore unsupported disk type like Ephemeral. It supports only os
            # disk. Calculate for iops, if it has value. If not, try disk size
            if disk_type_iops:
                if isinstance(self.data_disk_iops, int) or (
                    self.data_disk_iops != search_space.IntRange(min=0)
                ):
                    req_disk_iops = search_space.count_space_to_int_range(
                        self.data_disk_iops
                    )
                    cap_disk_iops = search_space.count_space_to_int_range(
                        capability.data_disk_iops
                    )
                    min_iops = max(req_disk_iops.min, cap_disk_iops.min)
                    max_iops = min(req_disk_iops.max, cap_disk_iops.max)

                    value.data_disk_iops = min(
                        iops
                        for iops, _ in disk_type_iops
                        if iops >= min_iops and iops <= max_iops
                    )
                    value.data_disk_size = self._get_disk_size_from_iops(
                        value.data_disk_iops, disk_type_iops
                    )
                elif self.data_disk_size:
                    req_disk_size = search_space.count_space_to_int_range(
                        self.data_disk_size
                    )
                    cap_disk_size = search_space.count_space_to_int_range(
                        capability.data_disk_size
                    )
                    min_size = max(req_disk_size.min, cap_disk_size.min)
                    max_size = min(req_disk_size.max, cap_disk_size.max)

                    value.data_disk_iops = min(
                        iops
                        for iops, disk_size in disk_type_iops
                        if disk_size >= min_size and disk_size <= max_size
                    )
                    value.data_disk_size = self._get_disk_size_from_iops(
                        value.data_disk_iops, disk_type_iops
                    )
                else:
                    # if req is not specified, query minimum value.
                    cap_disk_size = search_space.count_space_to_int_range(
                        capability.data_disk_size
                    )
                    value.data_disk_iops = min(
                        iops
                        for iops, _ in disk_type_iops
                        if iops >= cap_disk_size.min and iops <= cap_disk_size.max
                    )
                    value.data_disk_size = self._get_disk_size_from_iops(
                        value.data_disk_iops, disk_type_iops
                    )

        # all caching types are supported, so just take the value from requirement.
        value.data_disk_caching_type = self.data_disk_caching_type

        return value

    def _get_disk_size_from_iops(
        self, data_disk_iops: int, disk_type_iops: List[Tuple[int, int]]
    ) -> int:
        return next(
            disk_size for iops, disk_size in disk_type_iops if iops == data_disk_iops
        )
