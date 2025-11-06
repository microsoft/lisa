# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from lisa.executable import Tool


class Pvremove(Tool):
    @property
    def command(self) -> str:
        return "pvremove"

    @property
    def can_install(self) -> bool:
        return True

    def remove_pv(
        self, *devices: str, force: bool = True, ignore_errors: bool = False
    ) -> None:
        """
        Remove physical volume(s).

        Args:
            *devices: One or more device paths to remove as physical volumes
            force: If True, skip confirmation prompts (default: True)
            ignore_errors: If True, don't raise exception on errors (default: False)
        """
        cmd_parts = ["pvremove"]
        if force:
            cmd_parts.append("-f")
        cmd_parts.extend(devices)

        if ignore_errors:
            self.node.execute(" ".join(cmd_parts), sudo=True, no_error_log=True)
        else:
            self.node.execute(" ".join(cmd_parts), sudo=True, expected_exit_code=0)

    def _install(self) -> bool:
        self.node.os.install_packages("lvm2")
        return self._check_exists()
