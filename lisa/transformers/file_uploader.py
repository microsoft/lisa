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
from personal.lisa.lisa.parameter_parser import runbook

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

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        super()._initialize(*args, **kwargs)
        runbook: FileUploaderTransformerSchema = self.runbook
        
        #begin debug
        parent_dir = os.path.dirname(os.getcwd())
        print(f"[FileUploader DEBUG] Parent dir: {parent_dir}")
        try:
            print(f"[FileUploader DEBUG] Parent dir contents: {os.listdir(parent_dir)}")
        except Exception as e:
            print(f"[FileUploader DEBUG] Could not list parent dir contents: {e}")
        msft_lkt_path = os.path.join(parent_dir, "msft-lkt")
        print(f"[FileUploader DEBUG] msft-lkt at parent exists: {os.path.exists(msft_lkt_path)}")
        if os.path.exists(msft_lkt_path):
            print(f"[FileUploader DEBUG] msft-lkt at parent contents: {os.listdir(msft_lkt_path)}")
    
        # Debug: Print current working directory and source path
        print(f"[FileUploader DEBUG] Current working directory: {os.getcwd()}")
        print(f"[FileUploader DEBUG] runbook.source: {runbook.source}")
        # Debug: List contents of current working directory
        try:
            print(f"[FileUploader DEBUG] Contents of cwd: {os.listdir(os.getcwd())}")
        except Exception as e:
            print(f"[FileUploader DEBUG] Could not list cwd contents: {e}")
        # Debug: Check if msft-lkt exists and list contents
        msft_lkt_path = os.path.join(os.getcwd(), "msft-lkt")
        print(f"[FileUploader DEBUG] msft-lkt exists: {os.path.exists(msft_lkt_path)}")
        if os.path.exists(msft_lkt_path):
            try:
                print(f"[FileUploader DEBUG] msft-lkt contents: {os.listdir(msft_lkt_path)}")
            except Exception as e:
                print(f"[FileUploader DEBUG] Could not list msft-lkt contents: {e}")
        # Debug: Check if scripts directory exists and list contents
        scripts_path = os.path.join(os.getcwd(), "msft-lkt", "pipelines", "kernel-build", "scripts")
        print(f"[FileUploader DEBUG] scripts dir exists: {os.path.exists(scripts_path)}")
        if os.path.exists(scripts_path):
            try:
                print(f"[FileUploader DEBUG] scripts dir contents: {os.listdir(scripts_path)}")
            except Exception as e:
                print(f"[FileUploader DEBUG] Could not list scripts dir contents: {e}")
        # Debug: Check if verify_lvbs.sh exists
        verify_lvbs_path = os.path.join(scripts_path, "verify_lvbs.sh")
        print(f"[FileUploader DEBUG] verify_lvbs.sh exists: {os.path.exists(verify_lvbs_path)}")
        print(f"[FileUploader DEBUG] Absolute runbook.source: {os.path.abspath(runbook.source)}")
        #end debug

        if not runbook.source:
            raise ValueError("'source' must be provided.")
        if not runbook.destination:
            raise ValueError("'destination' must be provided.")
        if not runbook.files:
            raise ValueError("'files' must be provided.")

        if not os.path.exists(runbook.source):
            raise ValueError(f"source {runbook.source} doesn't exist.")

    def _internal_run(self) -> Dict[str, Any]:
        runbook: FileUploaderTransformerSchema = self.runbook
        result: Dict[str, Any] = dict()
        copy = self._node.tools[RemoteCopy]
        uploaded_files: List[str] = []

        self._log.debug(f"checking destination {runbook.destination}")
        ls = self._node.tools[Ls]
        if not ls.path_exists(runbook.destination):
            self._log.debug(f"creating directory {runbook.destination}")
            mkdir = self._node.tools[Mkdir]
            mkdir.create_directory(runbook.destination)

        for name in runbook.files:
            local_path = PurePath(runbook.source) / name
            remote_path = PurePath(runbook.destination)
            self._log.debug(f"uploading file from '{local_path}' to '{remote_path}'")

            copy.copy_to_remote(local_path, remote_path)
            uploaded_files.append(name)

        result[UPLOADED_FILES] = uploaded_files
        return result
