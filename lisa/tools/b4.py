import pathlib
import re
from lisa.executable import Tool
from lisa.operating_system import Posix
from lisa.util import get_matched_str


class B4(Tool):
    _output_file_pattern = re.compile(r"[\w-]+\.mbx")

    @property
    def command(self) -> str:
        return "b4"

    @property
    def can_install(self) -> bool:
        return True

    def _install(self) -> bool:
        if isinstance(self.node.os, Posix):
            self.node.os.install_packages("b4")
        return self._check_exists()

    def am(self, message_id: str, output_dir: pathlib.PurePath) -> pathlib.PurePath:
        result = self.run(
            f"am -o '{output_dir}' '{message_id}'", force_run=True, expected_exit_code=0
        )
        path_str = get_matched_str(result.stdout, self._output_file_pattern)
        return pathlib.PurePath(output_dir, path_str)
