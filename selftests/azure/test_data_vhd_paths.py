# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from unittest.case import TestCase

from lisa.sut_orchestrator.azure.common import DataVhdPath, VhdSchema
from lisa.util import SkippedException


class DataVhdPathsTestCase(TestCase):
    def test_data_vhd_path_schema(self) -> None:
        """Test DataVhdPath schema creation and serialization"""
        data_vhd = DataVhdPath(
            lun=0,
            vhd_uri="https://storageaccount.blob.core.windows.net/container/disk.vhd",
        )
        self.assertEqual(0, data_vhd.lun)
        self.assertIn("storageaccount", data_vhd.vhd_uri)

    def test_vhd_schema_with_data_vhd_paths(self) -> None:
        """Test VhdSchema with data_vhd_paths field"""
        vhd_schema = VhdSchema(
            vhd_path="https://storageaccount.blob.core.windows.net/container/os.vhd",
            data_vhd_paths=[
                DataVhdPath(
                    lun=0,
                    vhd_uri="https://storageaccount.blob.core.windows.net/container/data0.vhd",
                ),
                DataVhdPath(
                    lun=1,
                    vhd_uri="https://storageaccount.blob.core.windows.net/container/data1.vhd",
                ),
            ],
        )

        self.assertIsNotNone(vhd_schema.vhd_path)
        self.assertIsNotNone(vhd_schema.data_vhd_paths)
        self.assertEqual(2, len(vhd_schema.data_vhd_paths))
        self.assertEqual(0, vhd_schema.data_vhd_paths[0].lun)
        self.assertEqual(1, vhd_schema.data_vhd_paths[1].lun)

    def test_vhd_schema_serialization(self) -> None:
        """Test VhdSchema to_dict and from_dict with data_vhd_paths"""
        vhd_schema = VhdSchema(
            vhd_path="https://storageaccount.blob.core.windows.net/container/os.vhd",
            data_vhd_paths=[
                DataVhdPath(
                    lun=0,
                    vhd_uri="https://storageaccount.blob.core.windows.net/container/data0.vhd",
                )
            ],
        )

        # Convert to dict
        vhd_dict = vhd_schema.to_dict()
        self.assertIn("vhd_path", vhd_dict)
        self.assertIn("data_vhd_paths", vhd_dict)

        # Convert back from dict
        vhd_restored = VhdSchema.from_dict(vhd_dict)
        self.assertEqual(vhd_schema.vhd_path, vhd_restored.vhd_path)
        self.assertIsNotNone(vhd_restored.data_vhd_paths)
        if vhd_restored.data_vhd_paths:
            self.assertEqual(1, len(vhd_restored.data_vhd_paths))
            self.assertEqual(
                vhd_schema.data_vhd_paths[0].vhd_uri,
                vhd_restored.data_vhd_paths[0].vhd_uri,
            )

    def test_vhd_schema_without_data_vhd_paths(self) -> None:
        """Test VhdSchema without data_vhd_paths (backward compatibility)"""
        vhd_schema = VhdSchema(
            vhd_path="https://storageaccount.blob.core.windows.net/container/os.vhd"
        )

        self.assertIsNotNone(vhd_schema.vhd_path)
        # data_vhd_paths should be None by default
        self.assertIsNone(vhd_schema.data_vhd_paths)
