# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import os
from dataclasses import dataclass, field
from pathlib import PurePath
from typing import Any, Dict, List, Type

from dataclasses_json import dataclass_json

from lisa import schema
from lisa.tools import Ls, Mkdir, RemoteCopy
from lisa.transformers.deployment_transformer import (
    DeploymentTransformer,
    DeploymentTransformerSchema,
)

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
            f"files to upload: {self._runbook_files} from: {runbook.source}"
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
