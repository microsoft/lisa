import re
from typing import List

from lisa.feature import Feature
from lisa.tools import Lspci, Nvmecli
from lisa.tools.lspci import PciDevice

FEATURE_NAME_NESTED = "Nested"

class Nested(Feature):

    @classmethod
    def name(cls) -> str:
        return FEATURE_NAME_NESTED

    @classmethod
    def enabled(cls) -> bool:
        return True

    @classmethod
    def can_disable(cls) -> bool:
        return True

    def variable_exists(self, variable: str) -> bool:
        cmd_result = self.node.execute(f"-z {variable}")
        cmd_result.assert_exit_code(message=f"Please mention -{variable} next")
        return cmd_result.stdout
