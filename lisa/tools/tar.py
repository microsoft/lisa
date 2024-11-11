# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Callable, List, Optional, Type

from assertpy import assert_that

from lisa.executable import Tool
from lisa.operating_system import Suse
from lisa.tools.bzip2 import Bzip2
from lisa.tools.mkdir import Mkdir


class Tar(Tool):
    @property
    def command(self) -> str:
        return "tar"

    def _check_exists(self) -> bool:
        if isinstance(self.node.os, Suse):
            # ensure that bzip2 is installed on Suse
            _ = self.node.tools[Bzip2]

        return True

    @classmethod
    def _windows_tool(cls) -> Optional[Type[Tool]]:
        return WindowsTar

    def extract(
        self,
        file: str,
        dest_dir: str,
        strip_components: int = 0,
        gzip: bool = False,
        sudo: bool = False,
        raise_error: bool = True,
        skip_old_files: bool = False,
    ) -> None:
        # create folder when it doesn't exist
        assert_that(strip_components).described_as(
            "--strip-components arg for tar must be int >= 0"
        ).is_greater_than_or_equal_to(0)
        self.node.execute(f"mkdir -p {dest_dir}", shell=True)
        if gzip:
            tar_cmd = f"-zxvf {file} -C {dest_dir}"
        else:
            tar_cmd = f"-xvf {file} -C {dest_dir}"
        if strip_components:
            # optionally strip N top level components from a tar file
            tar_cmd += f" --strip-components={strip_components}"

        if skip_old_files:
            # NOTE:
            # This option is for when you are using
            #  Wget.get(..., force_run=False)
            #
            # Do not use this option if:
            # - You may need to extract multiple versions of a
            #   given tarball on a node
            # - You have provided a default output filename to Wget.get
            #   to fetch the tarball
            #
            # This skip-old-files option could silently skip extracting
            # the second version of the tarball.
            tar_cmd += " --skip-old-files"
        result = self.run(tar_cmd, shell=True, force_run=True, sudo=sudo)
        if raise_error:
            result.assert_exit_code(
                0, f"Failed to extract file to {dest_dir}, {result.stderr}"
            )

    def list(
        self, file: str, recursive: bool = True, folders_only: bool = False
    ) -> List[str]:
        # return a list of all the files and folders in a tar file
        result = self.run(
            f"-tf {file}",
            shell=True,
            force_run=True,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                f"Could not list items in tar file {file}"
            ),
        )

        # helper functions for processing stdout.splitlines()
        # folders are listed with trailing slashes, so:
        # ex: f1/f2/ f1/ f1/f2/f3/

        def is_folder(tar_content: str) -> bool:
            return tar_content.endswith("/")

        def get_file_depth(tar_content: str) -> int:
            slash_count = tar_content.count("/")
            if is_folder(tar_content):  # contains >= 1 slash
                return slash_count - 1
            else:
                return slash_count

        def is_top_level(tar_content: str) -> bool:
            return get_file_depth(tar_content) == 0

        content = result.stdout.splitlines()
        output: List[str] = []
        filters: List[Callable[[str], bool]] = []

        # assemble list of tests we need to apply
        if not recursive:
            filters.append(is_top_level)
        if folders_only:
            filters.append(is_folder)
        # if we need to test anything, add inputs that pass all tests
        if filters:
            for item in content:
                if all(func(item) for func in filters):
                    output.append(item)
            return output
        else:
            return content

    def get_root_folder(self, file: str) -> str:
        # convenience method, get the top level output folder
        # and remove the trailing slash
        # NOTE: Will assert if there are multiple root folders.
        folders = self.list(file, recursive=False, folders_only=True)
        assert_that(folders).described_as(
            (
                "ERROR: get_root_folder was called but tar file "
                f"{file} has multiple top level output folders."
            )
        ).is_length(1)
        return folders[0].replace("/", "")


class WindowsTar(Tar):
    def extract(
        self,
        file: str,
        dest_dir: str,
        strip_components: int = 0,
        gzip: bool = False,
        sudo: bool = False,
        raise_error: bool = True,
    ) -> None:
        mkdir = self.node.tools[Mkdir]
        mkdir.create_directory(dest_dir)

        tar_cmd = f"-xf {file} -C {dest_dir}"

        result = self.run(tar_cmd)
        if raise_error:
            result.assert_exit_code(
                expected_exit_code=0,
                message=f"Failed to extract file to {dest_dir}",
                include_output=True,
            )
