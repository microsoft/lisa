# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from pathlib import PurePath, PureWindowsPath
from typing import List, Type

from lisa import schema
from lisa.node import RemoteNode
from lisa.tools.ls import Ls
from lisa.tools.remote_copy import RemoteCopy
from lisa.tools.unzip import Unzip
from lisa.util import InitializableMixin, subclasses
from lisa.util.logger import get_logger

from .schema import LocalSourceSchema, SourceFileSchema, SourceSchema


class Source(subclasses.BaseClassWithRunbookMixin, InitializableMixin):
    def __init__(self, runbook: SourceSchema) -> None:
        super().__init__(runbook=runbook)
        self._log = get_logger("source", self.__class__.__name__)

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return SourceSchema

    def download(self, server: RemoteNode) -> List[PureWindowsPath]:
        raise NotImplementedError()


class LocalSource(Source):
    def __init__(self, runbook: LocalSourceSchema) -> None:
        super().__init__(runbook)
        self.local_runbook: LocalSourceSchema = self.runbook
        self._log = get_logger("local", self.__class__.__name__)
        self.downloaded_files: Optional[List[PureWindowsPath]] = None

    @classmethod
    def type_name(cls) -> str:
        return "local"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return LocalSourceSchema

    def download(self, server: RemoteNode) -> List[PureWindowsPath]:
        if not self.downloaded_files:
            self.downloaded_files = []

        for file in self.local_runbook.files:
            self.downloaded_files += self._download_file(file, server)

        return self.downloaded_files

    def _download_file(
        self, file: SourceFileSchema, server: RemoteNode
    ) -> List[PureWindowsPath]:
        local_path = PurePath(file.source)

        downloaded_paths: List[PurePath] = []

        if file.destination:
            if PureWindowsPath(file.destination).is_absolute():
                dest = PureWindowsPath(file.destination)
            else:
                dest = PureWindowsPath(server.working_path) / file.destination
        else:
            dest = PureWindowsPath(server.working_path) / "sources"

        downloaded_paths = server.tools[RemoteCopy].copy_to_remote(
            local_path, dest, recurse=True
        )

        if file.unzip:
            assert len(downloaded_paths) == 1
            zip_path = PureWindowsPath(downloaded_paths[0])
            server.tools[Unzip].extract(str(zip_path), str(zip_path.parent))
            server.shell.remove(zip_path)

            extracted_files = server.tools[Ls].list(str(zip_path.parent))

            return [zip_path.parent.joinpath(f) for f in extracted_files]

        return [PureWindowsPath(p) for p in downloaded_paths]
