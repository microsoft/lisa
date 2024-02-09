# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from pathlib import Path, PureWindowsPath
from typing import List, Optional, Type

from lisa import schema
from lisa.node import RemoteNode
from lisa.tools.ls import Ls
from lisa.tools.mkdir import Mkdir
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
        local_path = Path(file.source)

        local_files = []
        if local_path.is_dir():
            local_files = [f for f in local_path.iterdir() if f.is_file()]
        else:
            local_files = [local_path]

        downloaded_paths: List[PureWindowsPath] = []

        for f in local_files:
            downloaded_paths += self._download_single_file(
                f, file.destination, file.unzip, server
            )

        return downloaded_paths

    def _download_single_file(
        self,
        local_path: Path,
        destination: Optional[str],
        unzip: bool,
        server: RemoteNode,
    ) -> List[PureWindowsPath]:
        defined_destination = None
        if destination:
            if PureWindowsPath(destination).is_absolute():
                defined_destination = PureWindowsPath(destination)
            else:
                defined_destination = PureWindowsPath(server.working_path / destination)

        if unzip:
            dest_path = (
                PureWindowsPath(server.working_path)
                / "zipped_sources_tmp"
                / local_path.name
            )
        else:
            dest_path = PureWindowsPath(
                defined_destination / local_path.name
                if defined_destination
                else server.working_path / "sources" / local_path.name
            )

        server.tools[Mkdir].create_directory(str(dest_path.parent))

        self._log.debug(f"Copying {local_path} to server")
        server.shell.copy(local_path, dest_path)
        self._log.debug("Finished copying.")

        if unzip:
            final_destination = (
                defined_destination
                if defined_destination
                else PureWindowsPath(server.working_path) / "sources"
            )

            server.tools[Unzip].extract(str(dest_path), str(final_destination))
            server.shell.remove(dest_path)

            extracted_files = server.tools[Ls].list(str(final_destination))

            return [final_destination.joinpath(f) for f in extracted_files]

        return [dest_path]
