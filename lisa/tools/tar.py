# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from lisa.executable import Tool
from lisa.util import LisaException
from pathlib import Path


class Tar(Tool):
    @property
    def command(self) -> str:
        return "tar"

    def extract(
        self, file: str, dest_dir: PurePath, rename_tar_output_dir: str = ""
    ) -> str:
        # create folder when it doesn't exist
        mkdir_cmd = f"mkdir -p {dest_dir.as_posix()}"
        tar_cmd = f"-xvf {file}"

        # if we rename we need to:
        if rename_tar_output_dir:
            tar_output_path = dest_dir.joinpath(rename_tar_output_dir)
            # create the additional new output directory
            mkdir_cmd += f" {tar_output_path.as_posix()}"
            # assign the new output path as the dest
            dest_dir = tar_output_path
            # and add a flag to discard the tar's original top level dir
            tar_cmd += " --strip-components=1"
            # now the command will output the contents into our new output dir

        tar_cmd += f" -C {dest_dir}"
        # now, create the directories and run tar
        self.node.execute(mkdir_cmd, shell=True)
        result = self.run(tar_cmd, shell=True, force_run=True, sudo=True)
        if result.exit_code != 0:
            raise LisaException(
                f"Failed to extract file to {dest_dir}, {result.stderr}"
            )

        # Get the folder name of the extracted file
        if rename_tar_output_dir:
            return rename_tar_output_dir
        else:
            return result.stdout.split("/")[0]
