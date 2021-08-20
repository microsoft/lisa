# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

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


DiskEphemeral = schema.DiskOptionSettings(disk_type=schema.DiskType.Ephemeral)
DiskPremiumLRS = schema.DiskOptionSettings(disk_type=schema.DiskType.PremiumLRS)
DiskStandardHDDLRS = schema.DiskOptionSettings(disk_type=schema.DiskType.StandardHDDLRS)
DiskStandardSSDLRS = schema.DiskOptionSettings(disk_type=schema.DiskType.StandardSSDLRS)
