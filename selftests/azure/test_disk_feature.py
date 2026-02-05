# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import sys
from unittest.case import TestCase

from lisa import LisaException, constants, schema, search_space
from lisa.sut_orchestrator.azure import features


class AzureDiskFeatureTestCase(TestCase):
    def test_disk_type_no_disk_req(self) -> None:
        # no disk in req, the cap get from lowest cost StandardHDDLRS. iops and
        # disk size
        req = features.AzureDiskOptionSettings()
        cap = self._get_default_cap()
        self._assert_disk(
            req,
            cap,
            data_disk_count=0,
        )

    def test_disk_type_overlap(self) -> None:
        # req and cap both have DiskPremiumSSDLRS, so it's selected
        req = features.AzureDiskOptionSettings(
            data_disk_type=search_space.SetSpace[schema.DiskType](
                items=[schema.DiskType.PremiumSSDLRS, schema.DiskType.StandardSSDLRS]
            )
        )
        cap = self._get_default_cap()
        self._assert_disk(
            req,
            cap,
            data_disk_count=0,
            disk_type=schema.DiskType.PremiumSSDLRS,
            data_disk_iops=120,
            data_disk_size=4,
        )

    def test_disk_type_no_common(self) -> None:
        # req and cap has no common disk type
        req = features.AzureDiskOptionSettings(
            data_disk_type=search_space.SetSpace[schema.DiskType](
                items=[schema.DiskType.StandardSSDLRS]
            )
        )
        cap = self._get_default_cap()
        reason = req.check(cap)
        self.assertFalse(reason.result)
        with self.assertRaises(LisaException) as cm:
            req.generate_min_capability(cap)
        self.assertIsInstance(cm.exception, LisaException)
        self.assertIn("capability doesn't support requirement", str(cm.exception))

    def test_disk_one_default_data_disk(self) -> None:
        # 1 data disk in req, no value, the cap get from lowest cost
        # StandardHDDLRS, iops and disk size
        req = features.AzureDiskOptionSettings(
            data_disk_count=1,
        )
        cap = self._get_default_cap()
        self._assert_disk(
            req,
            cap,
        )

    def test_disk_specify_caching_type(self) -> None:
        # the caching type is defined by req, not cap
        req = features.AzureDiskOptionSettings(
            data_disk_caching_type=constants.DATADISK_CACHING_TYPE_READYWRITE,
            data_disk_count=1,
        )
        cap = self._get_default_cap()
        self._assert_disk(
            req,
            cap,
            data_disk_caching_type=constants.DATADISK_CACHING_TYPE_READYWRITE,
        )

    def test_disk_specify_iops_min_to_biggest(self) -> None:
        # given a min iops value, which can may only the biggest value.
        req = features.AzureDiskOptionSettings(
            data_disk_count=1,
            data_disk_iops=search_space.IntRange(min=1800),
        )
        cap = self._get_default_cap()
        self._assert_disk(req, cap, data_disk_iops=2000, data_disk_size=16384)

    def test_disk_specify_iops_a_range(self) -> None:
        # given a range of iops, match min one in range
        req = features.AzureDiskOptionSettings(
            data_disk_count=1,
            data_disk_type=schema.DiskType.PremiumSSDLRS,
            os_disk_type=schema.DiskType.PremiumSSDLRS,
            data_disk_iops=search_space.IntRange(min=1800, max=8000),
        )
        cap = self._get_default_cap()
        self._assert_disk(
            req,
            cap,
            disk_type=schema.DiskType.PremiumSSDLRS,
            data_disk_iops=2300,
            data_disk_size=512,
        )

    def test_disk_specify_iops_range_both_req_cap(self) -> None:
        # given a range of iops on req and cap, match min one in range
        req = features.AzureDiskOptionSettings(
            data_disk_count=1,
            data_disk_type=schema.DiskType.PremiumSSDLRS,
            os_disk_type=schema.DiskType.PremiumSSDLRS,
            data_disk_iops=search_space.IntRange(min=1800, max=8000),
        )
        cap = self._get_default_cap()
        cap.data_disk_iops = search_space.IntRange(min=4000, max=800000)
        self._assert_disk(
            req,
            cap,
            disk_type=schema.DiskType.PremiumSSDLRS,
            data_disk_iops=5000,
            data_disk_size=1024,
        )

    def test_disk_specify_iops_use_premium(self) -> None:
        # given premium disk type
        req = features.AzureDiskOptionSettings(
            data_disk_type=search_space.SetSpace[schema.DiskType](
                items=[schema.DiskType.PremiumSSDLRS]
            ),
            data_disk_count=1,
            data_disk_iops=search_space.IntRange(min=1800),
        )
        cap = self._get_default_cap()
        self._assert_disk(
            req,
            cap,
            disk_type=schema.DiskType.PremiumSSDLRS,
            data_disk_iops=2300,
            data_disk_size=512,
        )

    def test_disk_specify_disk_size_min_to_biggest(self) -> None:
        # given min value to disk size, match the max one
        req = features.AzureDiskOptionSettings(
            data_disk_count=1,
            data_disk_size=search_space.IntRange(min=9000),
        )
        cap = self._get_default_cap()
        self._assert_disk(
            req,
            cap,
            data_disk_iops=2000,
            data_disk_size=16384,
        )

    def test_disk_specify_disk_size_a_range(self) -> None:
        # given a range to disk size, match the min one in range
        req = features.AzureDiskOptionSettings(
            data_disk_type=search_space.SetSpace[schema.DiskType](
                items=[schema.DiskType.PremiumSSDLRS]
            ),
            data_disk_count=1,
            data_disk_size=search_space.IntRange(min=1500, max=30000),
        )
        cap = self._get_default_cap()
        self._assert_disk(
            req,
            cap,
            disk_type=schema.DiskType.PremiumSSDLRS,
            data_disk_iops=7500,
            data_disk_size=2048,
        )

    def _assert_disk(
        self,
        req: features.AzureDiskOptionSettings,
        cap: features.AzureDiskOptionSettings,
        disk_type: schema.DiskType = schema.DiskType.StandardHDDLRS,
        data_disk_count: int = 1,
        data_disk_caching_type: str = constants.DATADISK_CACHING_TYPE_NONE,
        data_disk_iops: int = 500,
        data_disk_size: int = 32,
    ) -> None:
        reason = req.check(cap)
        self.assertTrue(reason.result, f"check reasons: {reason.reasons}")
        min_value: features.AzureDiskOptionSettings = req.generate_min_capability(cap)
        self.assertEqual(disk_type, min_value.data_disk_type)
        self.assertEqual(data_disk_count, min_value.data_disk_count)
        self.assertEqual(data_disk_caching_type, min_value.data_disk_caching_type)
        self.assertEqual(data_disk_iops, min_value.data_disk_iops)
        self.assertEqual(data_disk_size, min_value.data_disk_size)

    def _get_default_cap(self) -> features.AzureDiskOptionSettings:
        return features.AzureDiskOptionSettings(
            data_disk_type=search_space.SetSpace[schema.DiskType](
                items=[schema.DiskType.PremiumSSDLRS, schema.DiskType.StandardHDDLRS]
            ),
            data_disk_iops=search_space.IntRange(max=sys.maxsize),
            data_disk_size=search_space.IntRange(max=sys.maxsize),
        )
