# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import os
import re
import zipfile
from pathlib import Path
from typing import List, Type

from lisa import schema
from lisa.advanced_tools.ado_artifact_download import ADOArtifactsDownloader
from lisa.node import local
from lisa.util import InitializableMixin, subclasses
from lisa.util.logger import get_logger

from .schema import ADOSourceSchema, SourceSchema


class Source(subclasses.BaseClassWithRunbookMixin, InitializableMixin):
    def __init__(self, runbook: SourceSchema) -> None:
        super().__init__(runbook=runbook)
        self._log = get_logger("source", self.__class__.__name__)

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return SourceSchema

    def download(self, timeout: int = 600) -> List[Path]:
        raise NotImplementedError()


class ADOSource(Source):
    __file_format = re.compile(r"format=(?P<format>.*)", re.M)

    def __init__(self, runbook: ADOSourceSchema) -> None:
        super().__init__(runbook)
        self.ado_runbook: ADOSourceSchema = self.runbook
        self._log = get_logger("ado", self.__class__.__name__)

    @classmethod
    def type_name(cls) -> str:
        return "ado"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return ADOSourceSchema

    def download(self, timeout: int = 600) -> List[Path]:
        personal_access_token = self.ado_runbook.pat
        organization_url = self.ado_runbook.organization_url
        project_name = self.ado_runbook.project
        artifacts = self.ado_runbook.artifacts
        build_id = self.ado_runbook.build_id
        pipeline_name = self.ado_runbook.pipeline_name
        ado = local().tools[ADOArtifactsDownloader]
        artifacts_path = ado.download(
            personal_access_token=personal_access_token,
            organization_url=organization_url,
            project_name=project_name,
            artifacts=[x.artifact_name for x in artifacts],
            build_id=build_id,
            pipeline_name=pipeline_name,
            timeout=timeout,
        )
        artifacts_path_raw = artifacts_path
        artifacts_path = []
        for artifact in artifacts:
            pattern = re.compile(rf".*{artifact.artifact_name}.*")
            for artifact_path in artifacts_path_raw:
                if pattern.match(str(artifact_path)):
                    self._log.info(f"Artifact downloaded to {str(artifact_path)}")
                    if artifact.extract:
                        source_path = self.extract(artifact_path)
                        artifacts_path.append(Path(source_path))
                    else:
                        artifacts_path.append(artifact_path)
        return artifacts_path

    def extract(self, artifact_path: Path) -> str:
        file_extension = artifact_path.suffix
        if file_extension == ".zip":
            with zipfile.ZipFile(str(artifact_path), "r") as zip_ref:
                zip_ref.extractall(str(artifact_path.parent))
        source_path = os.path.splitext(str(artifact_path))[0]
        self._log.info(f"Artifact extracted to {str(source_path)}")
        return source_path
