# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from contextlib import ExitStack, contextmanager
from typing import Any, Dict, Iterator, Optional
from unittest import TestCase, mock

from azure.mgmt.compute.models import GalleryImage, GalleryImageFeature

from lisa.sut_orchestrator.azure import common, transformers
from lisa.util import LisaException


class SharedGalleryImageTransformerTestCase(TestCase):
    def test_hibernation_requires_gen2_before_copying_vhd(self) -> None:
        with self._patch_azure() as mocks:
            with self.assertRaises(LisaException) as cm:
                self._run(gallery_image_hibernation_supported=True)
        self.assertIn("generation 2", str(cm.exception))
        self.assertIn("gallery_image_hyperv_generation", str(cm.exception))
        mocks["get_deployable_storage_path"].assert_not_called()
        mocks["check_or_create_gallery_image"].assert_not_called()

    def test_hibernation_gen1_marketplace_source_reported(self) -> None:
        marketplace_features = {"hyper_v_generation": 1, "architecture": "x64"}
        with self._patch_azure(marketplace_features):
            with self.assertRaises(LisaException) as cm:
                self._run(
                    gallery_image_hibernation_supported=True,
                    gallery_image_hyperv_generation=2,
                    marketplace_source="p o s latest",
                )
        self.assertIn("marketplace_source 'p o s latest'", str(cm.exception))

    def test_hibernation_keeps_default_disk_controller_types(self) -> None:
        with self._patch_azure() as mocks:
            self._run(
                gallery_image_hibernation_supported=True,
                gallery_image_hyperv_generation=2,
            )
        self.assertEqual(
            {
                "DiskControllerTypes": (
                    common.DEFAULT_GALLERY_IMAGE_DISK_CONTROLLER_TYPES
                ),
                "IsHibernateSupported": "True",
            },
            self._get_requested_features(mocks),
        )
        mocks["check_or_create_gallery_image_version"].assert_called_once()

    def test_hibernation_with_explicit_disk_controller_types(self) -> None:
        with self._patch_azure() as mocks:
            self._run(
                gallery_image_hibernation_supported=True,
                gallery_image_hyperv_generation=2,
                gallery_image_disk_controller_types="NVMe",
            )
        self.assertEqual(
            {"DiskControllerTypes": "NVMe", "IsHibernateSupported": "True"},
            self._get_requested_features(mocks),
        )

    def test_hibernation_disabled_adds_no_features(self) -> None:
        with self._patch_azure() as mocks:
            self._run()
        self.assertEqual({}, self._get_requested_features(mocks))

    def test_existing_definition_without_hibernation_fails(self) -> None:
        with self._patch_azure(
            mismatched_features={"IsHibernateSupported": None}
        ) as mocks:
            with self.assertRaises(LisaException) as cm:
                self._run(
                    gallery_image_hibernation_supported=True,
                    gallery_image_hyperv_generation=2,
                )
        self.assertIn("already exists", str(cm.exception))
        mocks["check_or_create_gallery_image_version"].assert_not_called()

    def test_existing_definition_other_mismatch_warns(self) -> None:
        with self._patch_azure(
            mismatched_features={"DiskControllerTypes": "SCSI"}
        ) as mocks:
            transformer = self._run(
                gallery_image_disk_controller_types="NVMe", run=False
            )
            with mock.patch.object(transformer, "_log") as log:
                transformer._internal_run()
        log.warning.assert_called_once()
        mocks["check_or_create_gallery_image_version"].assert_called_once()

    def test_get_mismatched_gallery_image_features(self) -> None:
        gallery_image = GalleryImage(
            location="westus3",
            features=[
                GalleryImageFeature(name="DiskControllerTypes", value="SCSI, NVMe"),
                GalleryImageFeature(name="isHibernateSupported", value="true"),
                GalleryImageFeature(name="SecurityType", value="Standard"),
            ],
        )
        mismatched = common._get_mismatched_gallery_image_features(
            gallery_image,
            {
                "DiskControllerTypes": "SCSI,NVMe",
                "IsHibernateSupported": "True",
                "SecurityType": "TrustedLaunch",
                "IsAcceleratedNetworkSupported": "True",
            },
        )
        self.assertEqual(
            {"SecurityType": "Standard", "IsAcceleratedNetworkSupported": None},
            mismatched,
        )

    def _run(
        self, run: bool = True, **kwargs: Any
    ) -> transformers.SharedGalleryImageTransformer:
        runbook = transformers.SigTransformerSchema(
            name="sig",
            type=transformers.SharedGalleryImageTransformer.type_name(),
            vhd="https://account.blob.core.windows.net/vhds/os.vhd",
            gallery_image_location=["westus3"],
            gallery_image_name="image",
            gallery_image_fullname="publisher offer sku 1.0.0",
            **kwargs,
        )
        transformer = transformers.SharedGalleryImageTransformer(
            runbook=runbook, runbook_builder=mock.MagicMock()
        )
        if run:
            transformer._internal_run()
        return transformer

    @contextmanager
    def _patch_azure(
        self,
        marketplace_features: Optional[Dict[str, Any]] = None,
        mismatched_features: Optional[Dict[str, Optional[str]]] = None,
    ) -> Iterator[Dict[str, mock.MagicMock]]:
        targets: Dict[str, Dict[str, Any]] = {
            "_load_platform": {},
            "get_deployable_storage_path": {
                "side_effect": lambda _platform, path, _location, _log: path
            },
            "get_vhd_details": {
                "return_value": {
                    "resource_group_name": "rg",
                    "account_name": "account",
                    "container_name": "vhds",
                    "blob_name": "os.vhd",
                }
            },
            "check_blob_exist": {},
            "check_or_create_resource_group": {},
            "check_or_create_gallery": {},
            "check_or_create_gallery_image": {
                "return_value": mismatched_features or {}
            },
            "check_or_create_gallery_image_version": {},
        }
        with ExitStack() as stack:
            mocks = {
                name: stack.enter_context(
                    mock.patch.object(transformers, name, **options)
                )
                for name, options in targets.items()
            }
            stack.enter_context(
                mock.patch.object(
                    transformers.SharedGalleryImageTransformer,
                    "_get_image_features",
                    return_value=dict(marketplace_features or {}),
                )
            )
            yield mocks

    def _get_requested_features(
        self, mocks: Dict[str, mock.MagicMock]
    ) -> Dict[str, Any]:
        call = mocks["check_or_create_gallery_image"].call_args
        features: Dict[str, Any] = call.args[12]
        return features
