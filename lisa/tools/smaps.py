import re
from typing import Dict

from lisa.executable import Tool
from lisa.util import LisaException


class Smaps(Tool):
    @property
    def command(self) -> str:
        return "cat"

    @property
    def can_install(self) -> bool:
        return False

    def get_page_sizes(self) -> Dict[str, int]:
        """Return the first mapping's page sizes in bytes, accepting LF or CRLF."""
        # Read once so both values describe the same mapping of the same process.
        result = self.run(
            str(self.node.get_pure_path("/proc/self/smaps")),
            force_run=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "Failed to read /proc/self/smaps. Check procfs availability and "
                "CONFIG_PROC_PAGE_MONITOR on the guest."
            ),
        )
        stdout = result.stdout.replace("\r\n", "\n")
        mappings = re.split(r"(?m)^[0-9a-f]+-[0-9a-f]+ ", stdout, maxsplit=2)
        if len(mappings) < 2:
            raise LisaException(
                "No process mapping found in /proc/self/smaps. "
                "Check procfs availability and CONFIG_PROC_PAGE_MONITOR on the guest."
            )

        page_sizes: Dict[str, int] = {}
        for field in ("KernelPageSize", "MMUPageSize"):
            match = re.search(
                rf"(?m)^{field}:[ \t]+([0-9]+)[ \t]+kB[ \t]*$", mappings[1]
            )
            if match is None:
                raise LisaException(
                    f"Missing or malformed {field} in the first smaps mapping. "
                    "Inspect /proc/self/smaps on the guest for a value in kB."
                )
            # procfs reports kB in units of 1024 bytes; getconf reports bytes.
            page_sizes[field] = int(match.group(1)) * 1024
        return page_sizes
