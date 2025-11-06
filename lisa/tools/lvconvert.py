# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

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
    ) -> None:
        """
        Attach a cache pool to an origin logical volume.

        Args:
            vg_name: Volume group name
            origin_lv: Origin logical volume name
            cache_pool_lv: Cache pool logical volume name
        """
        cmd_parts = ["lvconvert"]
        cmd_parts.append("--type cache")
        cmd_parts.append(f"--cachepool {vg_name}/{cache_pool_lv}")
        cmd_parts.append("-y")
        cmd_parts.append(f"{vg_name}/{origin_lv}")

        self.node.execute(" ".join(cmd_parts), sudo=True, expected_exit_code=0)

    def _install(self) -> bool:
        self.node.os.install_packages("lvm2")
        return self._check_exists()
