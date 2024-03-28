# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
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
            artifacts=artifacts,
            build_id=build_id,
            pipeline_name=pipeline_name,
            timeout=timeout,
        )
        return artifacts_path
