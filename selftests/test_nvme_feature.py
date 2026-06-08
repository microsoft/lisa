# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from unittest import TestCase
from unittest.mock import MagicMock, Mock

from lisa import schema
from lisa.features import Disk
from lisa.features.nvme import Nvme
from lisa.tools import Nvmecli


class NvmeFeatureTestCase(TestCase):
    def test_remove_nvme_remote_disks_filters_dual_controllers(self) -> None:
        nvme_feature = self._create_nvme_feature(
            disk_model_map={
                "/dev/nvme1n1": "MSFT NVMe Accelerator v1.0",
                "/dev/nvme2n1": "MSFT NVMe Accelerator v1.0",
                "/dev/nvme10n1": "Microsoft NVMe Direct Disk v2",
            },
            os_disk_namespace="/dev/nvme0n1",
            os_disk_controller="/dev/nvme0",
        )

        filtered = nvme_feature._remove_nvme_remote_disks(
            ["/dev/nvme0", "/dev/nvme1", "/dev/nvme2", "/dev/nvme10"]
        )

        self.assertEqual(["/dev/nvme10"], filtered)

    def test_remove_nvme_remote_disks_uses_exact_os_controller_match(self) -> None:
        nvme_feature = self._create_nvme_feature(
            disk_model_map={
                "/dev/nvme10n1": "Microsoft NVMe Direct Disk v2",
            },
            os_disk_namespace="/dev/nvme1n1",
            os_disk_controller="/dev/nvme1",
        )

        filtered = nvme_feature._remove_nvme_remote_disks(
            ["/dev/nvme1n1", "/dev/nvme10n1"]
        )

        self.assertEqual(["/dev/nvme10n1"], filtered)

    def _create_nvme_feature(
        self,
        disk_model_map: dict[str, str],
        os_disk_namespace: str,
        os_disk_controller: str,
    ) -> Nvme:
        disk_feature = Mock()
        disk_feature.get_os_disk_controller_type.return_value = (
            schema.DiskControllerType.NVME
        )

        nvme_cli = Mock()
        nvme_cli.get_device_models.return_value = disk_model_map
        nvme_cli.get_disk_model_map.return_value = disk_model_map

        node = Mock()
        node.log = Mock()
        node.features = MagicMock()
        node.features.__getitem__.side_effect = (
            lambda feature_type: disk_feature if feature_type is Disk else None
        )
        node.tools = MagicMock()
        node.tools.__getitem__.side_effect = (
            lambda tool_type: nvme_cli if tool_type is Nvmecli else None
        )

        nvme_feature = Nvme(schema.FeatureSettings.create(Nvme.name()), node, Mock())
        nvme_feature.get_os_disk_nvme_namespace = Mock(return_value=os_disk_namespace)
        nvme_feature.get_nvme_os_disk_controller = Mock(
            return_value=os_disk_controller
        )
        return nvme_feature