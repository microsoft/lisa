import pathlib
import re
from typing import List, Type

from lisa.executable import Tool
from lisa.operating_system import Debian
from lisa.tools.git import Git
from lisa.tools.python import Pip
from lisa.util import LisaException, find_group_in_lines


class B4(Tool):
    # Output log is of the form
    # git am /mnt/code/linux/v2_20241029_xxx_offers.mbx
    _output_file_pattern = re.compile(
        r"^.*git.*/(?P<filename>[\w-]+\.mbx).*$", re.MULTILINE
    )

    @property
    def command(self) -> str:
        return "b4"

    @property
    def dependencies(self) -> List[Type[Tool]]:
        return [Git]

    @property
    def can_install(self) -> bool:
        return True

    def _install(self) -> bool:
        if isinstance(self.node.os, Debian):
            self.node.os.install_packages("b4")
        installed = self._check_exists()
        if not installed:
            pip = self.node.tools[Pip]
            pip.install_packages("b4", install_to_user=True)
        return self._check_exists()

    def apply(
        self, message_id: str, cwd: pathlib.PurePath, sudo: bool = False
    ) -> pathlib.PurePath:
        """
        Download the patch using the message id and apply it to the git repository.
        """
        result = self.run(
            f"am -o '{cwd}' '{message_id}'",
            force_run=True,
            expected_exit_code=0,
            sudo=sudo,
        )
        filename = find_group_in_lines(
            lines=result.stdout, pattern=self._output_file_pattern, single_line=False
        ).get("filename")
        if not filename:
            raise LisaException("Failed to get filename from b4 am output")
        filepath = pathlib.PurePath(cwd, filename)

        git = self.node.tools[Git]
        git.apply(cwd=cwd, patches=filepath)

        return filepath
