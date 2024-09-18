# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import os
import re
from pathlib import Path, PurePath
from typing import Dict, List, Type

from smb.SMBConnection import SMBConnection  # type: ignore

from lisa import schema
from lisa.node import quick_connect
from lisa.tools import Ls, RemoteCopy
from lisa.util import ContextMixin, InitializableMixin, subclasses
from lisa.util.logger import get_logger

from .schema import BuildSchema, FileSchema, SMBBuildSchema, TftpBuildSchema


def _find_matched_files(
    sources_path: List[Path],
    files_map: List[FileSchema],
) -> Dict[str, FileSchema]:
    all_files = []
    match_files: Dict[str, FileSchema] = {}
    for source_path in sources_path:
        for root, _, files in os.walk(source_path):
            for file in files:
                all_files.append(os.path.join(root, file))

        for file_map in files_map:
            file_path = rf"{source_path}\{file_map.source}".replace("\\", "\\\\")
            pattern = re.compile(
                file_path,
                re.I | re.M,
            )
            for file in all_files:
                if pattern.match(file):
                    match_files[file] = file_map
    return match_files


class Build(subclasses.BaseClassWithRunbookMixin, ContextMixin, InitializableMixin):
    def __init__(self, runbook: BuildSchema) -> None:
        super().__init__(runbook=runbook)
        self._log = get_logger("cluster", self.__class__.__name__)

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return BuildSchema

    def copy(self, sources_path: List[Path], files_map: List[FileSchema]) -> None:
        raise NotImplementedError()


class SMBBuild(Build):
    def __init__(self, runbook: SMBBuildSchema) -> None:
        super().__init__(runbook)
        self.smb_runbook: SMBBuildSchema = self.runbook

    @classmethod
    def type_name(cls) -> str:
        return "smb"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return SMBBuildSchema

    def copy(self, sources_path: List[Path], files_map: List[FileSchema]) -> None:
        username = self.smb_runbook.username
        password = self.smb_runbook.password
        server_name = self.smb_runbook.server_name
        share_name = self.smb_runbook.share

        with SMBConnection(
            username=username,
            password=password,
            my_name="",
            remote_name=server_name,
        ) as conn:
            conn.connect(server_name)

            for file, file_map in _find_matched_files(
                sources_path,
                files_map,
            ).items():
                with open(file, "rb") as f:
                    if file_map.destination:
                        attrs = conn.getAttributes(
                            share_name, file_map.destination, timeout=30
                        )
                        if attrs.isDirectory:
                            file_name = (
                                file_map.destination + "\\" + file.rsplit("\\")[-1]
                            )
                        else:
                            file_name = file_map.destination
                        conn.storeFile(share_name, file_name, f)
                    else:
                        file_name = file.rsplit("\\")[-1]
                        conn.storeFile(
                            share_name,
                            file_name,
                            f,
                        )
                self._log.debug(f"copy file {file} to {share_name}\\{file_name}")


class TftpBuild(Build):
    def __init__(self, runbook: TftpBuildSchema) -> None:
        super().__init__(runbook)
        self.pxe_runbook: TftpBuildSchema = self.runbook

    @classmethod
    def type_name(cls) -> str:
        return "tftp"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return TftpBuildSchema

    def copy(self, sources_path: List[Path], files_map: List[FileSchema]) -> None:
        assert self.pxe_runbook.connection, "The build server is not specified"

        build_server = quick_connect(
            self.pxe_runbook.connection,
            logger_name="build_server",
        )

        ls = build_server.tools[Ls]
        rc = build_server.tools[RemoteCopy]
        self._log.debug(f"Copying files to: {build_server}")
        for file, file_map in _find_matched_files(
            sources_path,
            files_map,
        ).items():
            if file_map.destination:
                file_map_path = PurePath(file_map.destination)
                if ls.is_file(file_map_path):
                    file_destination = file_map_path.parent
                else:
                    file_destination = file_map_path
            else:
                file_destination = PurePath(file).parent

            rc.copy_to_remote(PurePath(file), file_destination)
        self._log.debug(f"Copied files to: {build_server}")
