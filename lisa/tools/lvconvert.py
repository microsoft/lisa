# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Optional

from lisa.executable import Tool


class Lvconvert(Tool):
    @property
    def command(self) -> str:
        return "lvconvert"

    @property
    def can_install(self) -> bool:
        return True

    def attach_cache(
        self,
        vg_name: str,
        origin_lv: str,
        cache_pool_lv: str,
        yes: bool = True,
    ) -> None:
        """
        Attach a cache pool to an origin logical volume.

        Args:
            vg_name: Volume group name
            origin_lv: Origin logical volume name
            cache_pool_lv: Cache pool logical volume name
            yes: If True, automatically answer yes to prompts (default: True)
        """
        cmd_parts = ["lvconvert"]
        cmd_parts.append("--type cache")
        cmd_parts.append(f"--cachepool {vg_name}/{cache_pool_lv}")
        if yes:
            cmd_parts.append("-y")
        cmd_parts.append(f"{vg_name}/{origin_lv}")

        self.node.execute(" ".join(cmd_parts), sudo=True, expected_exit_code=0)

    def convert(
        self,
        lv_path: str,
        conversion_type: Optional[str] = None,
        extra: str = "",
        yes: bool = True,
    ) -> None:
        """
        Generic lvconvert operation for various conversion types.

        Args:
            lv_path: Full path to the logical volume (e.g., "vgname/lvname")
            conversion_type: Type of conversion (e.g., "cache", "raid1", "mirror")
            extra: Additional parameters to pass to lvconvert
            yes: If True, automatically answer yes to prompts (default: True)
        """
        cmd_parts = ["lvconvert"]
        if conversion_type:
            cmd_parts.append(f"--type {conversion_type}")
        if yes:
            cmd_parts.append("-y")
        if extra:
            cmd_parts.append(extra)
        cmd_parts.append(lv_path)

        self.node.execute(" ".join(cmd_parts), sudo=True, expected_exit_code=0)

    def _install(self) -> bool:
        self.node.os.install_packages("lvm2")
        return self._check_exists()
