# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from functools import partial
from typing import Type

from lisa import schema
from lisa.feature import Feature


class Disk(Feature):
    @classmethod
    def settings_type(cls) -> Type[schema.FeatureSettings]:
        return schema.DiskOptionSettings

    @classmethod
    def can_disable(cls) -> bool:
        return False

    def enabled(self) -> bool:
        return True


DiskEphemeral = partial(schema.DiskOptionSettings, disk_type=schema.DiskType.Ephemeral)
DiskPremiumSSDLRS = partial(
    schema.DiskOptionSettings, disk_type=schema.DiskType.PremiumSSDLRS
)
DiskStandardHDDLRS = partial(
    schema.DiskOptionSettings, disk_type=schema.DiskType.StandardHDDLRS
)
DiskStandardSSDLRS = partial(
    schema.DiskOptionSettings, disk_type=schema.DiskType.StandardSSDLRS
)
