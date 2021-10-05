# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from functools import partial
from typing import Type

from lisa import schema
from lisa.feature import Feature
from lisa.tools import Mount
from lisa.util import get_matched_str


class Disk(Feature):

    # /dev/sda1 on / type ext4 (rw,relatime,discard)
    _os_disk_regex = re.compile(r"\s*\/dev\/(?P<partition>\D+).*\s+on\s+\/\s+type.*")

    @classmethod
    def settings_type(cls) -> Type[schema.FeatureSettings]:
        return schema.DiskOptionSettings

    @classmethod
    def can_disable(cls) -> bool:
        return False

    def enabled(self) -> bool:
        return True

    def get_os_disk(self) -> str:
        # os disk(root disk) is the entry with mount point `/' in the output
        # of `mount` command
        mount = self._node.tools[Mount].run().stdout
        os_disk = get_matched_str(mount, self._os_disk_regex)
        assert os_disk
        self._log.debug(f"OS disk: {os_disk}")
        return os_disk


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
