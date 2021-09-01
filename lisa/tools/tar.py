# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from lisa.executable import Tool
from lisa.util import LisaException


class Tar(Tool):
    @property
    def command(self) -> str:
        return "tar"

    def extract(self, file: str, dest_dir: str) -> str:
        # create folder when it doesn't exist
        self.node.execute(f"mkdir -p {dest_dir}", shell=True)
        result = self.run(
            f"-xvf {file} -C {dest_dir}", shell=True, force_run=True, sudo=True
        )
        if result.exit_code != 0:
            raise LisaException(
                f"Failed to extract file to {dest_dir}, {result.stderr}"
            )
        # Get the folder name of the extracted file
        source_name = result.stdout.split("/")[0]
        return source_name
