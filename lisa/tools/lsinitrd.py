# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from typing import Optional, cast

from lisa.base_tools import Uname
from lisa.executable import Tool
from lisa.operating_system import Posix
from lisa.tools import Find
from lisa.util import LisaException, find_patterns_in_lines, get_matched_str


class Lsinitrd(Tool):
    _non_comment_pattern = re.compile(r"^\s*[^#\s].*$", re.MULTILINE)
    _modules_dep_file_pattern = re.compile(
        r".*\s(?P<PATH>[^\s]*\/modules\.dep)\s*$", re.MULTILINE
    )

    @property
    def command(self) -> str:
        return "lsinitrd"

    @property
    def can_install(self) -> bool:
        return True

    def _install(self) -> bool:
        posix_os: Posix = cast(Posix, self.node.os)
        posix_os.install_packages("dracut-core")
        return self._check_exists()

    def has_module(
        self, module_file_name: str, initrd_file_path: Optional[str] = None
    ) -> bool:
        """
        1) Finds path of modules.dep in initrd
        2) Searches modules.dep for the module file name
        """
        if not initrd_file_path:
            initrd_file_path = self.find_initrd_file_path()

        assert initrd_file_path, "Could not find initrd file path"

        result = self.run(
            initrd_file_path,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=f"`lsinitrd {initrd_file_path}` failed.",
        )

        modules_dep_path = get_matched_str(
            result.stdout, self._modules_dep_file_pattern
        )

        if not modules_dep_path:
            raise LisaException(
                f"[lsinitrd] modules.dep could not be found. "
                f"Make sure the file is present in initrd image {initrd_file_path}."
            )

        result = self.run(
            f"-f {modules_dep_path} {initrd_file_path}",
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=f"`lsinitrd -f /{modules_dep_path} "
            f"{initrd_file_path}` failed.",
        )
        modules_required = find_patterns_in_lines(
            result.stdout, [self._non_comment_pattern]
        )

        return any(
            module_file_name in requirement for requirement in modules_required[0]
        )

    def find_initrd_file_path(self) -> str:
        node = self.node
        uname = node.tools[Uname]
        kernel_version = uname.get_linux_information().kernel_version_raw
        find = node.tools[Find]
        initrd_possible_file_names = [
            f"initrd-{kernel_version}",
            f"initramfs-{kernel_version}.img",
            f"initrd.img-{kernel_version}",
        ]

        for file_name in initrd_possible_file_names:
            cmd_result = find.find_files(
                node.get_pure_path("/boot"), file_name, sudo=True
            )
            if cmd_result and cmd_result[0]:
                return cmd_result[0]

        return ""
