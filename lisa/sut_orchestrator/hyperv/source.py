# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from pathlib import PurePath, PureWindowsPath
from typing import List, Type

from lisa import schema
from lisa.node import RemoteNode
from lisa.tools.ls import Ls
from lisa.tools.unzip import Unzip
from lisa.util import InitializableMixin, subclasses
from lisa.util.logger import get_logger

from .schema import LocalVHDSourceSchema, VHDSourceSchema


class VHDSource(subclasses.BaseClassWithRunbookMixin, InitializableMixin):
    def __init__(self, runbook: VHDSourceSchema) -> None:
        super().__init__(runbook=runbook)
        self._log = get_logger("source", self.__class__.__name__)

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return VHDSourceSchema

    def download(self, server: RemoteNode) -> List[PureWindowsPath]:
        raise NotImplementedError()


class LocalVHDSource(VHDSource):
    def __init__(self, runbook: LocalVHDSourceSchema) -> None:
        super().__init__(runbook)
        self.local_vhd_runbook: LocalVHDSourceSchema = self.runbook
        self._log = get_logger("local", self.__class__.__name__)

    @classmethod
    def type_name(cls) -> str:
        return "local"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return LocalVHDSourceSchema

    def download(self, server: RemoteNode) -> List[PureWindowsPath]:
        # Download the VHD onto the server and return the path
        vhd_local_path = PurePath(self.local_vhd_runbook.vhd_path)
        vhd_remote_path = PureWindowsPath(
            server.working_path / f"source_vhd{vhd_local_path.suffix}"
        )

        if self.local_vhd_runbook.extract:
            vhd_remote_path = PureWindowsPath(server.working_path / "zipped_vhd.zip")

        self._log.debug("Copying VHD to server")
        server.shell.copy(vhd_local_path, vhd_remote_path)
        self._log.debug("Finished copying VHD to server")

        if self.local_vhd_runbook.extract:
            vhd_remote_path = self._unzip_vhd(server, vhd_remote_path)

        return [vhd_remote_path]

    def _unzip_vhd(
        self, server: RemoteNode, zipped_vhd_path: PureWindowsPath
    ) -> PureWindowsPath:
        extraction_path = zipped_vhd_path.parent.joinpath("source_vhd")
        server.tools[Unzip].extract(str(zipped_vhd_path), str(extraction_path))

        extracted_files = server.tools[Ls].list(str(extraction_path))
        assert len(extracted_files) == 1

        extracted_vhd = PureWindowsPath(extracted_files[0])
        extracted_vhd = extraction_path.joinpath(extracted_vhd)

        server.shell.remove(zipped_vhd_path)

        return extracted_vhd
