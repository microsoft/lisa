# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import os
import re
import zipfile
from pathlib import Path
from typing import List, Optional, Type

import requests
from assertpy import assert_that
from azure.devops.connection import Connection  # type: ignore
from msrest.authentication import BasicAuthentication

from lisa.executable import Tool
from lisa.schema import Artifact
from lisa.util import constants, get_matched_str


class ADOArtifactsDownloader(Tool):
    __file_format = re.compile(r"format=(?P<format>.*)", re.M)

    @property
    def command(self) -> str:
        return "echo ado_artifact_download"

    @property
    def can_install(self) -> bool:
        return False

    def download(
        self,
        personal_access_token: str,
        organization_url: str,
        project_name: str,
        artifacts: List[Artifact],
        build_id: int,
        pipeline_name: str,
        timeout: int = 600,
    ) -> List[Path]:
        working_path = constants.RUN_LOCAL_WORKING_PATH
        credentials = BasicAuthentication("", personal_access_token)
        connection = Connection(base_url=organization_url, creds=credentials)

        pipeline_client = connection.clients_v6_0.get_pipelines_client()
        pipelines = pipeline_client.list_pipelines(project_name)

        if pipeline_name:
            found_pipeline = False
            pipeline = None
            for pipeline in pipelines:
                if pipeline.name == pipeline_name:
                    found_pipeline = True
                    break
            assert_that(found_pipeline).described_as(
                (
                    f"cannot found pipeline {pipeline_name} in project {project_name}, "
                    "please double check the names"
                )
            ).is_true()
            assert pipeline is not None, "pipeline cannot be None"
            pipeline_runs = pipeline_client.list_runs(
                pipeline_id=pipeline.id, project=project_name
            )
            assert_that(len(pipeline_runs)).described_as(
                f"no runs found for pipeline {pipeline_name}"
            ).is_not_zero()

            pipeline_run = [
                run
                for run in pipeline_runs
                if run.result == "succeeded" and run.state == "completed"
            ]
            assert_that(len(pipeline_run)).described_as(
                f"no succeeded and completed run found for pipeline {pipeline_name}"
            ).is_not_zero()
            build_id = pipeline_run[0].id

        build_client = connection.clients_v6_0.get_build_client()
        artifacts_path: List[Path] = []
        for artifact in artifacts:
            artifact_name = artifact.artifact_name
            build_artifact = build_client.get_artifact(
                project_name, build_id, artifact_name
            )
            download_url = build_artifact.resource.download_url
            self._log.debug(f"artifact download url: {download_url}")
            working_path.mkdir(parents=True, exist_ok=True)
            file_extension = get_matched_str(download_url, self.__file_format)
            artifact_path = working_path / f"{build_artifact.name}.{file_extension}"
            self._log.debug(f"start to download artifact to {artifact_path}")
            with open(
                artifact_path,
                "wb",
            ) as download_file:
                response = requests.get(
                    download_url, auth=("", personal_access_token), timeout=timeout
                )
                download_file.write(response.content)
            self._log.debug(f"downloaded artifact to {artifact_path}")
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

    @classmethod
    def _windows_tool(cls) -> Optional[Type[Tool]]:
        return WindowsADOArtifactsDownloader


class WindowsADOArtifactsDownloader(ADOArtifactsDownloader):
    @property
    def command(self) -> str:
        return "echo windows_ado_artifact_download"

    def _check_exists(self) -> bool:
        return True
