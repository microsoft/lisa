# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from pathlib import PurePath
from typing import Any, List, Type

from lisa import schema
from lisa.node import RemoteNode
from lisa.tools.ls import Ls
from lisa.tools.remote_copy import RemoteCopy
from lisa.tools.unzip import Unzip
from lisa.util import InitializableMixin, subclasses
from lisa.util.logger import Logger, get_logger

from .schema import LocalSourceSchema, SourceFileSchema, SourceSchema


class Source(subclasses.BaseClassWithRunbookMixin, InitializableMixin):
    def __init__(
        self, runbook: SourceSchema, parent_logger: Logger, **kwargs: Any
    ) -> None:
        super().__init__(runbook=runbook, **kwargs)
        self._log = get_logger("source", self.__class__.__name__, parent=parent_logger)

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return SourceSchema

    def download(self, server: RemoteNode) -> List[PurePath]:
        raise NotImplementedError()


class LocalSource(Source):
    @classmethod
    def type_name(cls) -> str:
        return "local"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return LocalSourceSchema

    def download(self, server: RemoteNode) -> List[PurePath]:
        _downloaded_files = []

        runbook: LocalSourceSchema = self.runbook
        for file in runbook.files:
            _downloaded_files += self._download_file(file, server)

        return _downloaded_files

    def _download_file(
        self, file: SourceFileSchema, server: RemoteNode
    ) -> List[PurePath]:
        local_path = PurePath(file.source)

        downloaded_paths: List[PurePath] = []

        if file.destination:
            dest = server.get_pure_path(file.destination)
            if not dest.is_absolute():
                dest = server.working_path / file.destination
        else:
            dest = server.working_path / "sources"

        downloaded_paths = server.tools[RemoteCopy].copy_to_remote(
            local_path, dest, recurse=True
        )

        if file.unzip:
            assert (
                len(downloaded_paths) == 1
            ), "only one file expected when unzip is true"

            zip_path = server.get_pure_path(str(downloaded_paths[0]))
            server.tools[Unzip].extract(str(zip_path), str(zip_path.parent))
            server.shell.remove(zip_path)

            extracted_files = server.tools[Ls].list(str(zip_path.parent))

            return [zip_path.parent.joinpath(f) for f in extracted_files]

        return downloaded_paths
