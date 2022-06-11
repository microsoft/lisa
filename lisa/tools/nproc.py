# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from lisa.executable import Tool


class Nproc(Tool):
    @property
    def command(self) -> str:
        return "nproc"

    def get_num_procs(self) -> int:
        result = self.run()
        return int(result.stdout)
