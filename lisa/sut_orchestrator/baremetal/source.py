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

from .schema import ADOSourceSchema, Artifact, LocalSourceSchema, SourceSchema


def _extract(artifact_path: Path) -> str:
    file_extension = artifact_path.suffix
    if file_extension == ".zip":
        with zipfile.ZipFile(str(artifact_path), "r") as zip_ref:
            zip_ref.extractall(str(artifact_path.parent))
    source_path = os.path.splitext(str(artifact_path))[0]
    return source_path


def _extract_artifacts(
    artifacts: List[Artifact],
    artifacts_path: List[Path],
) -> List[Path]:
    artifact_local_path: List[Path] = []

    for artifact in artifacts:
        pattern = re.compile(rf".*{artifact.artifact_name}.*")
        for artifact_path in artifacts_path:
            if pattern.match(artifact_path.absolute().as_posix()):
                if artifact.extract:
                    source_path = _extract(artifact_path)
                    artifact_local_path.append(Path(source_path))
                else:
                    artifact_local_path.append(artifact_path.parent)

    return artifact_local_path


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

        return _extract_artifacts(artifacts, artifacts_path)


class LocalSource(Source):
    def __init__(self, runbook: LocalSourceSchema) -> None:
        super().__init__(runbook)
        self.local_runbook: LocalSourceSchema = runbook
        self._log = get_logger("local", self.__class__.__name__)

    @classmethod
    def type_name(cls) -> str:
        return "local"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return LocalSourceSchema

    def download(self, timeout: int = 600) -> List[Path]:
        local_artifacts_path: List[Path] = []

        for artifact in self.local_runbook.artifacts:
            self._log.debug(f"artifact_debug: {artifact}")
            local_artifacts_path.append(Path(artifact.artifact_name))

        return _extract_artifacts(
            self.local_runbook.artifacts,
            local_artifacts_path,
        )
