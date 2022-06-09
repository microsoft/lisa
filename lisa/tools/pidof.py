from typing import List

from lisa.executable import Tool


class Pidof(Tool):
    @property
    def command(self) -> str:
        return "pidof"

    @property
    def can_install(self) -> bool:
        return False

    def get_pids(self, process_name: str, sudo: bool = False) -> List[str]:
        pids = []
        # it's fine to fail
        result = self.run(process_name, force_run=True, shell=True, sudo=sudo)
        if result.exit_code == 0:
            pids = [x.strip() for x in result.stdout.split(" ")]
        return pids
