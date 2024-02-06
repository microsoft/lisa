# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import uuid
from pathlib import Path, PureWindowsPath
from typing import List, Optional, Type

from lisa import schema
from lisa.node import RemoteNode
from lisa.tools.cp import Cp
from lisa.tools.ls import Ls
from lisa.tools.mkdir import Mkdir
from lisa.tools.powershell import PowerShell
from lisa.tools.rm import Rm
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
        if unzip:
            return self._download_zipped_file(local_path, destination, server)

        destination_is_dir = destination and (
            destination.endswith("/") or destination.endswith("\\")
        )

        defined_destination = None
        if destination:
            if PureWindowsPath(destination).is_absolute():
                defined_destination = PureWindowsPath(destination)
            else:
                defined_destination = PureWindowsPath(server.working_path / destination)

        dest_path = PureWindowsPath(
            defined_destination
            if defined_destination
            else server.working_path / "sources" / local_path.name
        )

        if destination_is_dir:
            dest_path = dest_path / local_path.name

        server.tools[Mkdir].create_directory(
            str(dest_path) if destination_is_dir else str(dest_path.parent)
        )

        self._log.debug(f"Copying {local_path} to server")
        server.shell.copy(local_path, dest_path)
        self._log.debug("Finished copying.")

        return [dest_path]

    def _download_zipped_file(
        self, local_path: Path, destination: Optional[str], server: RemoteNode
    ) -> List[PureWindowsPath]:
        destination_is_dir = destination and (
            destination.endswith("/") or destination.endswith("\\")
        )

        defined_destination = None
        if destination:
            if PureWindowsPath(destination).is_absolute():
                defined_destination = PureWindowsPath(destination)
            else:
                defined_destination = PureWindowsPath(server.working_path / destination)

        tmp_dest = PureWindowsPath(
            server.working_path / "zipped_sources_tmp" / local_path.name
        )

        server.tools[Mkdir].create_directory(str(tmp_dest.parent))

        server.shell.copy(local_path, tmp_dest)

        # if the destination is a directory, directly unzip the file(s) into it
        extraction_path = self._unzip_file(
            server, tmp_dest, defined_destination if destination_is_dir else None
        )

        extracted_files = server.tools[Ls].list(str(extraction_path))

        if destination_is_dir:
            # the files are already in the destination directory
            return [extraction_path.joinpath(f) for f in extracted_files]

        if not defined_destination:
            final_destination = PureWindowsPath(server.working_path / "sources")
            server.tools[Mkdir].create_directory(str(final_destination))
            server.tools[PowerShell].run_cmdlet(
                f"Copy-Item -Path '{extraction_path}\\*'"
                f"-Destination '{final_destination}\\' -Recurse"
            )
            server.tools[Rm].remove_file(f"{extraction_path}\\*")
            return [(final_destination / f) for f in extracted_files]

        # if the destination is not a directory and it is defined in the runbook,
        # then it has to be a single file.
        assert len(extracted_files) == 1
        final_destination = PureWindowsPath(
            server.working_path / "sources" / extracted_files[0]
        )

        self._log.debug(f"Copying {local_path} to server")
        server.tools[Cp].copy(extraction_path / extracted_files[0], final_destination)
        self._log.debug("Finished copying.")

        server.tools[Rm].remove_file(extracted_files[0])

        return [final_destination]

    def _unzip_file(
        self,
        server: RemoteNode,
        zipped_file: PureWindowsPath,
        destination_dir: Optional[PureWindowsPath] = None,
    ) -> PureWindowsPath:
        extraction_path = zipped_file.parent.joinpath(f"extracted-{uuid.uuid4()}")
        if destination_dir:
            extraction_path = destination_dir

        server.tools[Unzip].extract(str(zipped_file), str(extraction_path))

        server.shell.remove(zipped_file)

        return extraction_path
