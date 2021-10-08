import re
from typing import Any, List

from lisa.executable import Tool
from lisa.util import LisaException

class BlockDevice:
    def __init__(
        self,
        name: str,
        size: str,
        type: str,
    ) -> None:
        self.name = name
        self.size = size
        self.type = type
        

class Lsblk(Tool):
    # lsblk command example:
    # ~$ lsblk
    # NAME    MAJ:MIN RM   SIZE RO TYPE MOUNTPOINT
    # loop0     7:0    0  55.5M  1 loop 
    # loop1     7:1    0  55.4M  1 loop 
    # loop2     7:2    0 234.7M  1 loop 
    # sda       8:0    0   121G  0 disk 
    # ├─sda1    8:1    0 120.9G  0 part /etc/hosts
    # ├─sda14   8:14   0     4M  0 part 
    # └─sda15   8:15   0   106M  0 part
     
    def _initialize(self, *args: Any, **Kwargs: Any) -> None:
        self._command = "lsblk"

    @property
    def command(self) -> str:
        return self._command

    def _check_exists(self) -> bool:
        return True

    def get_blocks(self) -> List[BlockDevice]:
        result = self.run()
        if result.exit_code != 0:
            raise LisaException(f"{self._command} exited with non-zero code: {result.exit_code}")

        # Get blocks without title line
        blocks = result.stdout.splitlines()[1:]
        assert len(blocks) > 0

        output: List[BlockDevice] = []
        for block in blocks:
            block_info = block.strip().split()
            block_name = re.sub(r'[\W_]+', '', block_info[0])
            block_size = block_info[3]
            block_type = block_info[5]
            output.append(
                BlockDevice(
                    name = block_name, 
                    size = block_size, 
                    type = block_type)
            )
        return output

    

    