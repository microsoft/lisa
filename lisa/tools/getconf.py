from lisa.executable import Tool
from lisa.util import LisaException


class Getconf(Tool):
    @property
    def command(self) -> str:
        return "getconf"

    @property
    def can_install(self) -> bool:
        return False

    def get_page_size(self) -> int:
        result = self.run(
            "PAGE_SIZE",
            force_run=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "Failed to read the guest base page size. "
                "Check that 'getconf PAGE_SIZE' succeeds on the guest."
            ),
        )
        try:
            return int(result.stdout.strip())
        except ValueError as error:
            raise LisaException(
                f"Invalid page size from getconf: {result.stdout!r}. "
                "Check 'getconf PAGE_SIZE' on the guest for an integer byte count."
            ) from error
