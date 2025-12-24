# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import os
from dataclasses import dataclass, field
from pathlib import PurePath
from typing import Any, Dict, List, Optional, Type

from dataclasses_json import dataclass_json

from lisa import schema
from lisa.node import RemoteNode, quick_connect
from lisa.tools import Ls, Mkdir, RemoteCopy
from lisa.transformers.deployment_transformer import (
    DeploymentTransformer,
    DeploymentTransformerSchema,
)
from lisa.util import field_metadata

FILE_UPLOADER = "file_uploader"
UPLOADED_FILES = "uploaded_files"


@dataclass_json
@dataclass
class FileUploaderTransformerSchema(DeploymentTransformerSchema):
    # source path of files to be uploaded
    source: str = ""
    # destination path of files to be uploaded
    destination: str = ""
    # uploaded files
    files: List[str] = field(default_factory=list)


class FileUploaderTransformer(DeploymentTransformer):
    """
    This transformer upload files from local to remote. It should be used when
    environment is connected.
    """

    @classmethod
    def type_name(cls) -> str:
        return FILE_UPLOADER

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return FileUploaderTransformerSchema

    @property
    def _output_names(self) -> List[str]:
        return [UPLOADED_FILES]

    def _check_dest_dir(self, dest_path: str) -> None:
        self._log.debug(f"checking destination {dest_path}")
        ls = self._node.tools[Ls]
        if not ls.path_exists(dest_path):
            self._log.debug(f"creating directory {dest_path}")
            mkdir = self._node.tools[Mkdir]
            mkdir.create_directory(dest_path)

    def _validate(self) -> None:
        runbook: FileUploaderTransformerSchema = self.runbook
        source: PurePath = PurePath(runbook.source)

        if not os.path.exists(runbook.source):
            raise ValueError(f"source {runbook.source} doesn't exist.")

        self._runbook_files: List[str] = runbook.files
        if self._runbook_files == ["*"]:
            self._runbook_files = []
            files = os.listdir(runbook.source)
            if len(files) == 0:
                self._log.info("No files to upload")
            for file in files:
                self._runbook_files.append(file)

        for file in self._runbook_files:
            assert os.path.exists(source / file), f"Node does not contain file: {file}"

        self._log.debug(
            f"files to upload: {self._runbook_files} from:" f"{runbook.source}"
        )

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        super()._initialize(*args, **kwargs)
        runbook: FileUploaderTransformerSchema = self.runbook
        if not runbook.source:
            raise ValueError("'source' must be provided.")
        if not runbook.destination:
            raise ValueError("'destination' must be provided.")
        if not runbook.files:
            raise ValueError("'files' must be provided.")

        self._validate()

    def _internal_run(self) -> Dict[str, Any]:
        runbook: FileUploaderTransformerSchema = self.runbook
        result: Dict[str, Any] = dict()
        copy = self._node.tools[RemoteCopy]
        uploaded_files: List[str] = []
        destination_path = runbook.destination

        self._check_dest_dir(destination_path)

        for name in self._runbook_files:
            local_path = PurePath(runbook.source) / name
            remote_path = PurePath(destination_path)
            self._log.debug(f"uploading file from '{local_path}' to '{remote_path}'")

            copy.copy_to_remote(local_path, remote_path)
            uploaded_files.append(name)

        result[UPLOADED_FILES] = uploaded_files
        return result


FILE_TRANSFER = "file_transfer"
TRANSFERRED_FILES = "transferred_files"


@dataclass_json
@dataclass
class FileTransferTransformerSchema(FileUploaderTransformerSchema):
    # optional source node information, use schema.RemoteNode
    source_node: schema.RemoteNode = field(
        default_factory=schema.RemoteNode,
        metadata=field_metadata(required=True),
    )
    # optional local path for temporary storage during file transfers
    local_path: Optional[str] = ""
    # flag to skip scp attempts
    try_scp: Optional[bool] = True


class FileTransferTransformer(FileUploaderTransformer):
    """
    This transformer transfers files between two remotes. It should be used when
    environment is connected.
    """

    @classmethod
    def type_name(cls) -> str:
        return FILE_TRANSFER

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return FileTransferTransformerSchema

    @property
    def _output_names(self) -> List[str]:
        return [TRANSFERRED_FILES]

    def _validate(self) -> None:
        runbook: FileTransferTransformerSchema = self.runbook
        source = runbook.source

        # Cache the connected source node on the instance to avoid reconnecting.
        self._source_node = quick_connect(runbook.source_node, runbook.name)
        src_node = self._source_node

        ls = src_node.tools[Ls]
        if not ls.path_exists(source):
            raise ValueError(f"source {source} doesn't exist on remote node.")

        self._runbook_files: List[str] = runbook.files
        if self._runbook_files == ["*"]:
            self._runbook_files = []
            files = ls.list(source, sudo=True)
            if len(files) == 0:
                self._log.debug("No files to transfer.")
            for file in files:
                self._runbook_files.append(PurePath(file).name)

        for file in self._runbook_files:
            assert ls.path_exists(
                f"{source}/{file}"
            ), f"Node does not contain file: {file}"

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        super()._initialize(*args, **kwargs)
        runbook: FileTransferTransformerSchema = self.runbook
        if not runbook.source_node:
            raise ValueError("'source_node' must be provided.")

    def _internal_run(self) -> Dict[str, Any]:
        runbook: FileTransferTransformerSchema = self.runbook
        result: Dict[str, Any] = dict()
        dest_copy = self._node.tools[RemoteCopy]
        transferred_files: List[str] = []

        src_purepath = PurePath(runbook.source)
        dest_node = self._node
        dest_purepath = PurePath(runbook.destination)

        # checking destination existence
        self._check_dest_dir(runbook.destination)

        src_node = self._source_node
        src_copy = src_node.tools[RemoteCopy]
        local_purepath = None
        if runbook.local_path:
            if not os.path.exists(runbook.local_path):
                os.mkdir(runbook.local_path)

            local_path = f"{runbook.local_path}/{src_purepath.name}"
            if not os.path.exists(local_path):
                os.mkdir(local_path)

            local_purepath = PurePath(local_path)

        scp_result: Optional[int] = 0
        if not runbook.try_scp:
            scp_result = -1

        for file_name in self._runbook_files:
            if scp_result is not None and scp_result == 0:
                self._log.info(
                    f"remote-to-remote: '{file_name}' to '{str(dest_purepath)}'"
                )
                scp_result = dest_copy.copy_between_remotes(
                    src_node=src_node,
                    src_path=src_purepath / file_name,
                    dest_node=dest_node,
                    dest_path=dest_purepath / file_name,
                    recurse=False,
                )
            else:
                assert local_purepath, "local path doesn't exist"
                self._log.info(f"downloading '{file_name}' from '{str(src_purepath)}")
                src_copy.copy_to_local(
                    src=src_purepath / file_name,
                    dest=local_purepath,
                    recurse=False,
                    sudo=False,
                )
                self._log.info(f"uploading '{file_name}' to '{str(dest_purepath)}'")
                dest_copy.copy_to_remote(
                    src=local_purepath / file_name,
                    dest=dest_purepath,
                    recurse=False,
                    sudo=False,
                )
            transferred_files.append(file_name)

        self._log.info(f"files transferred: {transferred_files}")
        result[TRANSFERRED_FILES] = transferred_files
        return result
